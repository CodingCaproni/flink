################################################################################
#  Licensed to the Apache Software Foundation (ASF) under one
#  or more contributor license agreements.  See the NOTICE file
#  distributed with this work for additional information
#  regarding copyright ownership.  The ASF licenses this file
#  to you under the Apache License, Version 2.0 (the
#  "License"); you may not use this file except in compliance
#  with the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
# limitations under the License.
################################################################################
from abc import ABC, abstractmethod

from pyflink.common import typeinfo, Duration, WatermarkStrategy, ConfigOptions
from pyflink.common.serialization import JsonRowDeserializationSchema, \
    JsonRowSerializationSchema, Encoder, SimpleStringSchema
from pyflink.common.typeinfo import Types
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors import FlinkKafkaConsumer, FlinkKafkaProducer, JdbcSink, \
    JdbcConnectionOptions, JdbcExecutionOptions, StreamingFileSink, \
    OutputFileConfig, FileSource, StreamFormat, FileEnumeratorProvider, FileSplitAssignerProvider, \
    NumberSequenceSource, RollingPolicy, FileSink, BucketAssigner, RMQSink, RMQSource, \
    RMQConnectionConfig, PulsarSource, StartCursor, PulsarDeserializationSchema, StopCursor, \
    SubscriptionType, PulsarSink, PulsarSerializationSchema, DeliveryGuarantee, TopicRoutingMode, \
    MessageDelayer
from pyflink.datastream.tests.test_util import DataStreamTestSinkFunction
from pyflink.java_gateway import get_gateway
from pyflink.testing.test_case_utils import PyFlinkTestCase, _load_specific_flink_module_jars, \
    invoke_java_object_method
from pyflink.util.java_utils import load_java_class, get_field_value, is_instance_of


class ConnectorTestBase(PyFlinkTestCase, ABC):

    @classmethod
    @abstractmethod
    def _get_jars_relative_path(cls):
        """
        Return the relative path of connector, such as `/flink-connectors/flink-sql-connector-jdbc`.
        """
        pass

    def setUp(self) -> None:
        self.env = StreamExecutionEnvironment.get_execution_environment()
        # Cache current ContextClassLoader, we will replace it with a temporary URLClassLoader to
        # load specific connector jars with given module path to do dependency isolation. And We
        # will change the ClassLoader back to the cached ContextClassLoader after the test case
        # finished.
        self._cxt_clz_loader = get_gateway().jvm.Thread.currentThread().getContextClassLoader()
        _load_specific_flink_module_jars(self._get_jars_relative_path())

    def tearDown(self):
        # Change the ClassLoader back to the cached ContextClassLoader after the test case finished.
        if self._cxt_clz_loader is not None:
            get_gateway().jvm.Thread.currentThread().setContextClassLoader(self._cxt_clz_loader)


class FlinkKafkaTest(ConnectorTestBase):

    @classmethod
    def _get_jars_relative_path(cls):
        return '/flink-connectors/flink-sql-connector-kafka'

    def setUp(self) -> None:
        super().setUp()
        self.env.set_parallelism(2)

    def test_kafka_connector_universal(self):
        self.kafka_connector_assertion(FlinkKafkaConsumer, FlinkKafkaProducer)

    def kafka_connector_assertion(self, flink_kafka_consumer_clz, flink_kafka_producer_clz):
        source_topic = 'test_source_topic'
        sink_topic = 'test_sink_topic'
        props = {'bootstrap.servers': 'localhost:9092', 'group.id': 'test_group'}
        type_info = Types.ROW([Types.INT(), Types.STRING()])

        # Test for kafka consumer
        deserialization_schema = JsonRowDeserializationSchema.builder() \
            .type_info(type_info=type_info).build()

        flink_kafka_consumer = flink_kafka_consumer_clz(source_topic, deserialization_schema, props)
        flink_kafka_consumer.set_start_from_earliest()
        flink_kafka_consumer.set_commit_offsets_on_checkpoints(True)

        j_properties = get_field_value(flink_kafka_consumer.get_java_function(), 'properties')
        self.assertEqual('localhost:9092', j_properties.getProperty('bootstrap.servers'))
        self.assertEqual('test_group', j_properties.getProperty('group.id'))
        self.assertTrue(get_field_value(flink_kafka_consumer.get_java_function(),
                                        'enableCommitOnCheckpoints'))
        j_start_up_mode = get_field_value(flink_kafka_consumer.get_java_function(), 'startupMode')

        j_deserializer = get_field_value(flink_kafka_consumer.get_java_function(), 'deserializer')
        j_deserialize_type_info = invoke_java_object_method(j_deserializer, "getProducedType")
        deserialize_type_info = typeinfo._from_java_type(j_deserialize_type_info)
        self.assertTrue(deserialize_type_info == type_info)
        self.assertTrue(j_start_up_mode.equals(get_gateway().jvm
                                               .org.apache.flink.streaming.connectors
                                               .kafka.config.StartupMode.EARLIEST))
        j_topic_desc = get_field_value(flink_kafka_consumer.get_java_function(),
                                       'topicsDescriptor')
        j_topics = invoke_java_object_method(j_topic_desc, 'getFixedTopics')
        self.assertEqual(['test_source_topic'], list(j_topics))

        # Test for kafka producer
        serialization_schema = JsonRowSerializationSchema.builder().with_type_info(type_info) \
            .build()
        flink_kafka_producer = flink_kafka_producer_clz(sink_topic, serialization_schema, props)
        flink_kafka_producer.set_write_timestamp_to_kafka(False)

        j_producer_config = get_field_value(flink_kafka_producer.get_java_function(),
                                            'producerConfig')
        self.assertEqual('localhost:9092', j_producer_config.getProperty('bootstrap.servers'))
        self.assertEqual('test_group', j_producer_config.getProperty('group.id'))
        self.assertFalse(get_field_value(flink_kafka_producer.get_java_function(),
                                         'writeTimestampToKafka'))


class FlinkJdbcSinkTest(ConnectorTestBase):

    @classmethod
    def _get_jars_relative_path(cls):
        return '/flink-connectors/flink-connector-jdbc'

    def test_jdbc_sink(self):
        ds = self.env.from_collection([('ab', 1), ('bdc', 2), ('cfgs', 3), ('deeefg', 4)],
                                      type_info=Types.ROW([Types.STRING(), Types.INT()]))
        jdbc_connection_options = JdbcConnectionOptions.JdbcConnectionOptionsBuilder()\
            .with_driver_name('com.mysql.jdbc.Driver')\
            .with_user_name('root')\
            .with_password('password')\
            .with_url('jdbc:mysql://server-name:server-port/database-name').build()

        jdbc_execution_options = JdbcExecutionOptions.builder().with_batch_interval_ms(2000)\
            .with_batch_size(100).with_max_retries(5).build()
        jdbc_sink = JdbcSink.sink("insert into test table", ds.get_type(), jdbc_connection_options,
                                  jdbc_execution_options)

        ds.add_sink(jdbc_sink).name('jdbc sink')
        plan = eval(self.env.get_execution_plan())
        self.assertEqual('Sink: jdbc sink', plan['nodes'][1]['type'])
        j_output_format = get_field_value(jdbc_sink.get_java_function(), 'outputFormat')

        connection_options = JdbcConnectionOptions(
            get_field_value(get_field_value(j_output_format, 'connectionProvider'),
                            'jdbcOptions'))
        self.assertEqual(jdbc_connection_options.get_db_url(), connection_options.get_db_url())
        self.assertEqual(jdbc_connection_options.get_driver_name(),
                         connection_options.get_driver_name())
        self.assertEqual(jdbc_connection_options.get_password(), connection_options.get_password())
        self.assertEqual(jdbc_connection_options.get_user_name(),
                         connection_options.get_user_name())

        exec_options = JdbcExecutionOptions(get_field_value(j_output_format, 'executionOptions'))
        self.assertEqual(jdbc_execution_options.get_batch_interval_ms(),
                         exec_options.get_batch_interval_ms())
        self.assertEqual(jdbc_execution_options.get_batch_size(),
                         exec_options.get_batch_size())
        self.assertEqual(jdbc_execution_options.get_max_retries(),
                         exec_options.get_max_retries())


class FlinkPulsarTest(ConnectorTestBase):

    @classmethod
    def _get_jars_relative_path(cls):
        return '/flink-connectors/flink-sql-connector-pulsar'

    def test_pulsar_source(self):
        TEST_OPTION_NAME = 'pulsar.source.enableAutoAcknowledgeMessage'
        pulsar_source = PulsarSource.builder() \
            .set_service_url('pulsar://localhost:6650') \
            .set_admin_url('http://localhost:8080') \
            .set_topics('ada') \
            .set_start_cursor(StartCursor.earliest()) \
            .set_unbounded_stop_cursor(StopCursor.never()) \
            .set_bounded_stop_cursor(StopCursor.at_event_time(22)) \
            .set_subscription_name('ff') \
            .set_subscription_type(SubscriptionType.Exclusive) \
            .set_deserialization_schema(
                PulsarDeserializationSchema.flink_type_info(Types.STRING(), None)) \
            .set_deserialization_schema(
                PulsarDeserializationSchema.flink_schema(SimpleStringSchema())) \
            .set_config(TEST_OPTION_NAME, True) \
            .set_properties({'pulsar.source.autoCommitCursorInterval': '1000'}) \
            .build()

        ds = self.env.from_source(source=pulsar_source,
                                  watermark_strategy=WatermarkStrategy.for_monotonous_timestamps(),
                                  source_name="pulsar source")
        ds.print()
        plan = eval(self.env.get_execution_plan())
        self.assertEqual('Source: pulsar source', plan['nodes'][0]['type'])

        configuration = get_field_value(pulsar_source.get_java_function(), "sourceConfiguration")
        self.assertEqual(
            configuration.getString(
                ConfigOptions.key('pulsar.client.serviceUrl')
                .string_type()
                .no_default_value()._j_config_option), 'pulsar://localhost:6650')
        self.assertEqual(
            configuration.getString(
                ConfigOptions.key('pulsar.admin.adminUrl')
                .string_type()
                .no_default_value()._j_config_option), 'http://localhost:8080')
        self.assertEqual(
            configuration.getString(
                ConfigOptions.key('pulsar.consumer.subscriptionName')
                .string_type()
                .no_default_value()._j_config_option), 'ff')
        self.assertEqual(
            configuration.getString(
                ConfigOptions.key('pulsar.consumer.subscriptionType')
                .string_type()
                .no_default_value()._j_config_option), SubscriptionType.Exclusive.name)
        test_option = ConfigOptions.key(TEST_OPTION_NAME).boolean_type().no_default_value()
        self.assertEqual(
            configuration.getBoolean(
                test_option._j_config_option), True)
        self.assertEqual(
            configuration.getLong(
                ConfigOptions.key('pulsar.source.autoCommitCursorInterval')
                .long_type()
                .no_default_value()._j_config_option), 1000)

    def test_source_set_topics_with_list(self):
        PulsarSource.builder() \
            .set_service_url('pulsar://localhost:6650') \
            .set_admin_url('http://localhost:8080') \
            .set_topics(['ada', 'beta']) \
            .set_subscription_name('ff') \
            .set_deserialization_schema(
                PulsarDeserializationSchema.flink_schema(SimpleStringSchema())) \
            .build()

    def test_source_set_topics_pattern(self):
        PulsarSource.builder() \
            .set_service_url('pulsar://localhost:6650') \
            .set_admin_url('http://localhost:8080') \
            .set_topics_pattern('ada.*') \
            .set_subscription_name('ff') \
            .set_deserialization_schema(
                PulsarDeserializationSchema.flink_schema(SimpleStringSchema())) \
            .build()

    def test_source_deprecated_method(self):
        test_option = ConfigOptions.key('pulsar.source.enableAutoAcknowledgeMessage') \
            .boolean_type().no_default_value()
        pulsar_source = PulsarSource.builder() \
            .set_service_url('pulsar://localhost:6650') \
            .set_admin_url('http://localhost:8080') \
            .set_topics('ada') \
            .set_deserialization_schema(
                PulsarDeserializationSchema.flink_type_info(Types.STRING(), None)) \
            .set_subscription_name('ff') \
            .set_config(test_option, True) \
            .set_config_with_dict({'pulsar.source.autoCommitCursorInterval': '1000'}) \
            .build()
        configuration = get_field_value(pulsar_source.get_java_function(), "sourceConfiguration")
        self.assertEqual(
            configuration.getBoolean(
                test_option._j_config_option), True)
        self.assertEqual(
            configuration.getLong(
                ConfigOptions.key('pulsar.source.autoCommitCursorInterval')
                .long_type()
                .no_default_value()._j_config_option), 1000)

    def test_pulsar_sink(self):
        ds = self.env.from_collection([('ab', 1), ('bdc', 2), ('cfgs', 3), ('deeefg', 4)],
                                      type_info=Types.ROW([Types.STRING(), Types.INT()]))

        TEST_OPTION_NAME = 'pulsar.producer.chunkingEnabled'
        pulsar_sink = PulsarSink.builder() \
            .set_service_url('pulsar://localhost:6650') \
            .set_admin_url('http://localhost:8080') \
            .set_producer_name('fo') \
            .set_topics('ada') \
            .set_serialization_schema(
                PulsarSerializationSchema.flink_schema(SimpleStringSchema())) \
            .set_delivery_guarantee(DeliveryGuarantee.AT_LEAST_ONCE) \
            .set_topic_routing_mode(TopicRoutingMode.ROUND_ROBIN) \
            .delay_sending_message(MessageDelayer.fixed(Duration.of_seconds(12))) \
            .set_config(TEST_OPTION_NAME, True) \
            .set_properties({'pulsar.producer.batchingMaxMessages': '100'}) \
            .build()

        ds.sink_to(pulsar_sink).name('pulsar sink')

        plan = eval(self.env.get_execution_plan())
        self.assertEqual('pulsar sink: Writer', plan['nodes'][1]['type'])
        configuration = get_field_value(pulsar_sink.get_java_function(), "sinkConfiguration")
        self.assertEqual(
            configuration.getString(
                ConfigOptions.key('pulsar.client.serviceUrl')
                .string_type()
                .no_default_value()._j_config_option), 'pulsar://localhost:6650')
        self.assertEqual(
            configuration.getString(
                ConfigOptions.key('pulsar.admin.adminUrl')
                .string_type()
                .no_default_value()._j_config_option), 'http://localhost:8080')
        self.assertEqual(
            configuration.getString(
                ConfigOptions.key('pulsar.producer.producerName')
                .string_type()
                .no_default_value()._j_config_option), 'fo - %s')

        j_pulsar_serialization_schema = get_field_value(
            pulsar_sink.get_java_function(), 'serializationSchema')
        j_serialization_schema = get_field_value(
            j_pulsar_serialization_schema, 'serializationSchema')
        self.assertTrue(
            is_instance_of(
                j_serialization_schema,
                'org.apache.flink.api.common.serialization.SimpleStringSchema'))

        self.assertEqual(
            configuration.getString(
                ConfigOptions.key('pulsar.sink.deliveryGuarantee')
                .string_type()
                .no_default_value()._j_config_option), 'at-least-once')

        j_topic_router = get_field_value(pulsar_sink.get_java_function(), "topicRouter")
        self.assertTrue(
            is_instance_of(
                j_topic_router,
                'org.apache.flink.connector.pulsar.sink.writer.router.RoundRobinTopicRouter'))

        j_message_delayer = get_field_value(pulsar_sink.get_java_function(), 'messageDelayer')
        delay_duration = get_field_value(j_message_delayer, 'delayDuration')
        self.assertEqual(delay_duration, 12000)

        test_option = ConfigOptions.key(TEST_OPTION_NAME).boolean_type().no_default_value()
        self.assertEqual(
            configuration.getBoolean(
                test_option._j_config_option), True)
        self.assertEqual(
            configuration.getLong(
                ConfigOptions.key('pulsar.producer.batchingMaxMessages')
                .long_type()
                .no_default_value()._j_config_option), 100)

    def test_sink_set_topics_with_list(self):
        PulsarSink.builder() \
            .set_service_url('pulsar://localhost:6650') \
            .set_admin_url('http://localhost:8080') \
            .set_topics(['ada', 'beta']) \
            .set_serialization_schema(
                PulsarSerializationSchema.flink_schema(SimpleStringSchema())) \
            .build()


class RMQTest(ConnectorTestBase):

    @classmethod
    def _get_jars_relative_path(cls):
        return '/flink-connectors/flink-sql-connector-rabbitmq'

    def test_rabbitmq_connectors(self):
        connection_config = RMQConnectionConfig.Builder() \
            .set_host('localhost') \
            .set_port(5672) \
            .set_virtual_host('/') \
            .set_user_name('guest') \
            .set_password('guest') \
            .build()
        type_info = Types.ROW([Types.INT(), Types.STRING()])
        deserialization_schema = JsonRowDeserializationSchema.builder() \
            .type_info(type_info=type_info).build()

        rmq_source = RMQSource(
            connection_config, 'source_queue', True, deserialization_schema)
        self.assertEqual(
            get_field_value(rmq_source.get_java_function(), 'queueName'), 'source_queue')
        self.assertTrue(get_field_value(rmq_source.get_java_function(), 'usesCorrelationId'))

        serialization_schema = JsonRowSerializationSchema.builder().with_type_info(type_info) \
            .build()
        rmq_sink = RMQSink(connection_config, 'sink_queue', serialization_schema)
        self.assertEqual(
            get_field_value(rmq_sink.get_java_function(), 'queueName'), 'sink_queue')


class ConnectorTests(PyFlinkTestCase):

    def setUp(self) -> None:
        self.env = StreamExecutionEnvironment.get_execution_environment()
        self.test_sink = DataStreamTestSinkFunction()
        _load_specific_flink_module_jars('/flink-connectors/flink-connector-files')
        _load_specific_flink_module_jars('/flink-connectors/flink-connector-sink-common')

    def tearDown(self) -> None:
        self.test_sink.clear()

    def test_stream_file_sink(self):
        self.env.set_parallelism(2)
        ds = self.env.from_collection([('ab', 1), ('bdc', 2), ('cfgs', 3), ('deeefg', 4)],
                                      type_info=Types.ROW([Types.STRING(), Types.INT()]))
        ds.map(
            lambda a: a[0],
            Types.STRING()).add_sink(
            StreamingFileSink.for_row_format(self.tempdir, Encoder.simple_string_encoder())
                .with_rolling_policy(
                    RollingPolicy.default_rolling_policy(
                        part_size=1024 * 1024 * 1024,
                        rollover_interval=15 * 60 * 1000,
                        inactivity_interval=5 * 60 * 1000))
                .with_output_file_config(
                    OutputFileConfig.OutputFileConfigBuilder()
                    .with_part_prefix("prefix")
                    .with_part_suffix("suffix").build()).build())

        self.env.execute("test_streaming_file_sink")

        results = []
        import os
        for root, dirs, files in os.walk(self.tempdir, topdown=True):
            for file in files:
                self.assertTrue(file.startswith('.prefix'))
                self.assertTrue('suffix' in file)
                path = root + "/" + file
                with open(path) as infile:
                    for line in infile:
                        results.append(line)

        expected = ['deeefg\n', 'bdc\n', 'ab\n', 'cfgs\n']
        results.sort()
        expected.sort()
        self.assertEqual(expected, results)

    def test_file_source(self):
        stream_format = StreamFormat.text_line_format()
        paths = ["/tmp/1.txt", "/tmp/2.txt"]
        file_source_builder = FileSource.for_record_stream_format(stream_format, *paths)
        file_source = file_source_builder\
            .monitor_continuously(Duration.of_days(1)) \
            .set_file_enumerator(FileEnumeratorProvider.default_splittable_file_enumerator()) \
            .set_split_assigner(FileSplitAssignerProvider.locality_aware_split_assigner()) \
            .build()

        continuous_setting = file_source.get_java_function().getContinuousEnumerationSettings()
        self.assertIsNotNone(continuous_setting)
        self.assertEqual(Duration.of_days(1), Duration(continuous_setting.getDiscoveryInterval()))

        input_paths_field = \
            load_java_class("org.apache.flink.connector.file.src.AbstractFileSource"). \
            getDeclaredField("inputPaths")
        input_paths_field.setAccessible(True)
        input_paths = input_paths_field.get(file_source.get_java_function())
        self.assertEqual(len(input_paths), len(paths))
        self.assertEqual(str(input_paths[0]), paths[0])
        self.assertEqual(str(input_paths[1]), paths[1])

    def test_file_sink(self):
        base_path = "/tmp/1.txt"
        encoder = Encoder.simple_string_encoder()
        file_sink_builder = FileSink.for_row_format(base_path, encoder)
        file_sink = file_sink_builder\
            .with_bucket_check_interval(1000) \
            .with_bucket_assigner(BucketAssigner.base_path_bucket_assigner()) \
            .with_rolling_policy(RollingPolicy.on_checkpoint_rolling_policy()) \
            .with_output_file_config(
                OutputFileConfig.builder().with_part_prefix("pre").with_part_suffix("suf").build())\
            .build()

        buckets_builder_field = \
            load_java_class("org.apache.flink.connector.file.sink.FileSink"). \
            getDeclaredField("bucketsBuilder")
        buckets_builder_field.setAccessible(True)
        buckets_builder = buckets_builder_field.get(file_sink.get_java_function())

        self.assertEqual("DefaultRowFormatBuilder", buckets_builder.getClass().getSimpleName())

        row_format_builder_clz = load_java_class(
            "org.apache.flink.connector.file.sink.FileSink$RowFormatBuilder")
        encoder_field = row_format_builder_clz.getDeclaredField("encoder")
        encoder_field.setAccessible(True)
        self.assertEqual("SimpleStringEncoder",
                         encoder_field.get(buckets_builder).getClass().getSimpleName())

        interval_field = row_format_builder_clz.getDeclaredField("bucketCheckInterval")
        interval_field.setAccessible(True)
        self.assertEqual(1000, interval_field.get(buckets_builder))

        bucket_assigner_field = row_format_builder_clz.getDeclaredField("bucketAssigner")
        bucket_assigner_field.setAccessible(True)
        self.assertEqual("BasePathBucketAssigner",
                         bucket_assigner_field.get(buckets_builder).getClass().getSimpleName())

        rolling_policy_field = row_format_builder_clz.getDeclaredField("rollingPolicy")
        rolling_policy_field.setAccessible(True)
        self.assertEqual("OnCheckpointRollingPolicy",
                         rolling_policy_field.get(buckets_builder).getClass().getSimpleName())

        output_file_config_field = row_format_builder_clz.getDeclaredField("outputFileConfig")
        output_file_config_field.setAccessible(True)
        output_file_config = output_file_config_field.get(buckets_builder)
        self.assertEqual("pre", output_file_config.getPartPrefix())
        self.assertEqual("suf", output_file_config.getPartSuffix())

    def test_seq_source(self):
        seq_source = NumberSequenceSource(1, 10)

        seq_source_clz = load_java_class(
            "org.apache.flink.api.connector.source.lib.NumberSequenceSource")
        from_field = seq_source_clz.getDeclaredField("from")
        from_field.setAccessible(True)
        self.assertEqual(1, from_field.get(seq_source.get_java_function()))

        to_field = seq_source_clz.getDeclaredField("to")
        to_field.setAccessible(True)
        self.assertEqual(10, to_field.get(seq_source.get_java_function()))
