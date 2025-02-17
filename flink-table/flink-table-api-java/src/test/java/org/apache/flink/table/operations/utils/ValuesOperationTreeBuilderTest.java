/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.apache.flink.table.operations.utils;

import org.apache.flink.table.annotation.DataTypeHint;
import org.apache.flink.table.annotation.FunctionHint;
import org.apache.flink.table.api.DataTypes;
import org.apache.flink.table.api.TableConfig;
import org.apache.flink.table.api.ValidationException;
import org.apache.flink.table.catalog.Column;
import org.apache.flink.table.catalog.ResolvedSchema;
import org.apache.flink.table.expressions.CallExpression;
import org.apache.flink.table.expressions.Expression;
import org.apache.flink.table.expressions.ResolvedExpression;
import org.apache.flink.table.functions.BuiltInFunctionDefinitions;
import org.apache.flink.table.functions.ScalarFunction;
import org.apache.flink.table.operations.ValuesQueryOperation;
import org.apache.flink.table.types.DataType;
import org.apache.flink.table.types.utils.DataTypeFactoryMock;
import org.apache.flink.table.utils.FunctionLookupMock;
import org.apache.flink.types.Row;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

import javax.annotation.Nullable;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.Arrays;
import java.util.Collections;
import java.util.Optional;
import java.util.stream.Stream;

import static java.util.Arrays.asList;
import static java.util.Collections.singletonList;
import static org.apache.flink.table.api.Expressions.call;
import static org.apache.flink.table.api.Expressions.row;
import static org.apache.flink.table.expressions.ApiExpressionUtils.typeLiteral;
import static org.apache.flink.table.expressions.ApiExpressionUtils.valueLiteral;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** Tests for {@link OperationTreeBuilder#values}. */
public class ValuesOperationTreeBuilderTest {

    static Stream<TestSpec> parameters() {
        return Stream.of(
                TestSpec.test("Flattening row constructor")
                        .values(row(1, "ABC"), row(2, "EFG"))
                        .equalTo(
                                new ValuesQueryOperation(
                                        asList(
                                                asList(valueLiteral(1), valueLiteral("ABC")),
                                                asList(valueLiteral(2), valueLiteral("EFG"))),
                                        ResolvedSchema.of(
                                                Column.physical("f0", DataTypes.INT().notNull()),
                                                Column.physical(
                                                        "f1", DataTypes.CHAR(3).notNull())))),
                TestSpec.test("Finding common type")
                        .values(row(1L, "ABC"), row(3.1f, "DEFG"))
                        .equalTo(
                                new ValuesQueryOperation(
                                        asList(
                                                asList(
                                                        cast(
                                                                valueLiteral(1L),
                                                                DataTypes.FLOAT().notNull()),
                                                        valueLiteral(
                                                                "ABC",
                                                                DataTypes.VARCHAR(4).notNull())),
                                                asList(
                                                        valueLiteral(3.1f),
                                                        valueLiteral(
                                                                "DEFG",
                                                                DataTypes.VARCHAR(4).notNull()))),
                                        ResolvedSchema.of(
                                                Column.physical("f0", DataTypes.FLOAT().notNull()),
                                                Column.physical(
                                                        "f1", DataTypes.VARCHAR(4).notNull())))),
                TestSpec.test("Explicit common type")
                        .values(
                                DataTypes.ROW(
                                        DataTypes.FIELD("id", DataTypes.DECIMAL(10, 2)),
                                        DataTypes.FIELD("name", DataTypes.STRING())),
                                row(1L, "ABC"),
                                row(3.1f, "DEFG"))
                        .equalTo(
                                new ValuesQueryOperation(
                                        asList(
                                                asList(
                                                        cast(
                                                                valueLiteral(1L),
                                                                DataTypes.DECIMAL(10, 2)),
                                                        cast(
                                                                valueLiteral(
                                                                        "ABC",
                                                                        DataTypes.STRING()
                                                                                .notNull()),
                                                                DataTypes.STRING())),
                                                asList(
                                                        cast(
                                                                valueLiteral(3.1f),
                                                                DataTypes.DECIMAL(10, 2)),
                                                        cast(
                                                                valueLiteral(
                                                                        "DEFG",
                                                                        DataTypes.STRING()
                                                                                .notNull()),
                                                                DataTypes.STRING()))),
                                        ResolvedSchema.of(
                                                Column.physical("id", DataTypes.DECIMAL(10, 2)),
                                                Column.physical("name", DataTypes.STRING())))),
                TestSpec.test("Explicit common type for nested rows")
                        .values(
                                DataTypes.ROW(
                                        DataTypes.FIELD("id", DataTypes.DECIMAL(10, 2)),
                                        DataTypes.FIELD(
                                                "details",
                                                DataTypes.ROW(
                                                        DataTypes.FIELD("name", DataTypes.STRING()),
                                                        DataTypes.FIELD(
                                                                "amount",
                                                                DataTypes.DECIMAL(10, 2))))),
                                row(1L, row("ABC", 3)),
                                row(3.1f, row("DEFG", new BigDecimal("12345"))))
                        .equalTo(
                                new ValuesQueryOperation(
                                        asList(
                                                asList(
                                                        cast(
                                                                valueLiteral(1L),
                                                                DataTypes.DECIMAL(10, 2)),
                                                        rowCtor(
                                                                DataTypes.ROW(
                                                                        DataTypes.FIELD(
                                                                                "name",
                                                                                DataTypes.STRING()),
                                                                        DataTypes.FIELD(
                                                                                "amount",
                                                                                DataTypes.DECIMAL(
                                                                                        10, 2))),
                                                                cast(
                                                                        valueLiteral(
                                                                                "ABC",
                                                                                DataTypes.STRING()
                                                                                        .notNull()),
                                                                        DataTypes.STRING()),
                                                                cast(
                                                                        valueLiteral(3),
                                                                        DataTypes.DECIMAL(10, 2)))),
                                                asList(
                                                        cast(
                                                                valueLiteral(3.1f),
                                                                DataTypes.DECIMAL(10, 2)),
                                                        rowCtor(
                                                                DataTypes.ROW(
                                                                        DataTypes.FIELD(
                                                                                "name",
                                                                                DataTypes.STRING()),
                                                                        DataTypes.FIELD(
                                                                                "amount",
                                                                                DataTypes.DECIMAL(
                                                                                        10, 2))),
                                                                cast(
                                                                        valueLiteral(
                                                                                "DEFG",
                                                                                DataTypes.STRING()
                                                                                        .notNull()),
                                                                        DataTypes.STRING()),
                                                                cast(
                                                                        valueLiteral(
                                                                                new BigDecimal(
                                                                                        "12345"),
                                                                                DataTypes.DECIMAL(
                                                                                                10,
                                                                                                2)
                                                                                        .notNull()),
                                                                        DataTypes.DECIMAL(
                                                                                10, 2))))),
                                        ResolvedSchema.of(
                                                Column.physical("id", DataTypes.DECIMAL(10, 2)),
                                                Column.physical(
                                                        "details",
                                                        DataTypes.ROW(
                                                                DataTypes.FIELD(
                                                                        "name", DataTypes.STRING()),
                                                                DataTypes.FIELD(
                                                                        "amount",
                                                                        DataTypes.DECIMAL(
                                                                                10, 2))))))),
                TestSpec.test("Finding a common type for nested rows")
                        .values(row(1L, row(1L, "ABC")), row(3.1f, row(3.1f, "DEFG")))
                        .equalTo(
                                new ValuesQueryOperation(
                                        asList(
                                                asList(
                                                        cast(
                                                                valueLiteral(1L),
                                                                DataTypes.FLOAT().notNull()),
                                                        rowCtor(
                                                                DataTypes.ROW(
                                                                                DataTypes.FIELD(
                                                                                        "f0",
                                                                                        DataTypes
                                                                                                .FLOAT()
                                                                                                .notNull()),
                                                                                DataTypes.FIELD(
                                                                                        "f1",
                                                                                        DataTypes
                                                                                                .VARCHAR(
                                                                                                        4)
                                                                                                .notNull()))
                                                                        .notNull(),
                                                                cast(
                                                                        valueLiteral(1L),
                                                                        DataTypes.FLOAT()
                                                                                .notNull()),
                                                                valueLiteral(
                                                                        "ABC",
                                                                        DataTypes.VARCHAR(4)
                                                                                .notNull()))),
                                                asList(
                                                        valueLiteral(3.1f),
                                                        rowCtor(
                                                                DataTypes.ROW(
                                                                                DataTypes.FIELD(
                                                                                        "f0",
                                                                                        DataTypes
                                                                                                .FLOAT()
                                                                                                .notNull()),
                                                                                DataTypes.FIELD(
                                                                                        "f1",
                                                                                        DataTypes
                                                                                                .VARCHAR(
                                                                                                        4)
                                                                                                .notNull()))
                                                                        .notNull(),
                                                                valueLiteral(
                                                                        3.1f,
                                                                        DataTypes.FLOAT()
                                                                                .notNull()),
                                                                valueLiteral(
                                                                        "DEFG",
                                                                        DataTypes.VARCHAR(4)
                                                                                .notNull())))),
                                        ResolvedSchema.of(
                                                Column.physical("f0", DataTypes.FLOAT().notNull()),
                                                Column.physical(
                                                        "f1",
                                                        DataTypes.ROW(
                                                                        DataTypes.FIELD(
                                                                                "f0",
                                                                                DataTypes.FLOAT()
                                                                                        .notNull()),
                                                                        DataTypes.FIELD(
                                                                                "f1",
                                                                                DataTypes.VARCHAR(4)
                                                                                        .notNull()))
                                                                .notNull())))),
                TestSpec.test("Finding common type. Insert cast for calls")
                        .values(call(new IntScalarFunction()), row(3.1f))
                        .equalTo(
                                new ValuesQueryOperation(
                                        asList(
                                                singletonList(
                                                        cast(
                                                                CallExpression.anonymous(
                                                                        new IntScalarFunction(),
                                                                        Collections.emptyList(),
                                                                        DataTypes.INT()),
                                                                DataTypes.FLOAT())),
                                                singletonList(
                                                        cast(
                                                                valueLiteral(3.1f),
                                                                DataTypes.FLOAT()))),
                                        ResolvedSchema.of(
                                                Column.physical("f0", DataTypes.FLOAT())))),
                TestSpec.test("Row in a function result is not flattened")
                        .values(call(new RowScalarFunction()))
                        .equalTo(
                                new ValuesQueryOperation(
                                        singletonList(
                                                singletonList(
                                                        CallExpression.anonymous(
                                                                new RowScalarFunction(),
                                                                Collections.emptyList(),
                                                                DataTypes.ROW(
                                                                        DataTypes.FIELD(
                                                                                "f0",
                                                                                DataTypes.INT()),
                                                                        DataTypes.FIELD(
                                                                                "f1",
                                                                                DataTypes
                                                                                        .STRING()))))),
                                        ResolvedSchema.of(
                                                Column.physical(
                                                        "f0",
                                                        DataTypes.ROW(
                                                                DataTypes.FIELD(
                                                                        "f0", DataTypes.INT()),
                                                                DataTypes.FIELD(
                                                                        "f1",
                                                                        DataTypes.STRING())))))),
                TestSpec.test("Cannot find a common super type")
                        .values(
                                valueLiteral(LocalTime.of(1, 1)),
                                valueLiteral(LocalDate.of(1, 1, 1)))
                        .expectValidationException(
                                "Types in fromValues(...) must have a common super type. Could not find a common type"
                                        + " for all rows at column 0.\n"
                                        + "Could not find a common super type for types: [TIME(0) NOT NULL, DATE NOT NULL]"),
                TestSpec.test("Cannot find a common super type in a nested row")
                        .values(
                                row(1, row(3, valueLiteral(LocalTime.of(1, 1)))),
                                row(1, row(4, valueLiteral(LocalTime.of(2, 1)))),
                                row(2D, row(2.0, valueLiteral(LocalDate.of(1, 1, 1)))))
                        .expectValidationException(
                                "Types in fromValues(...) must have a common super type. Could not find a common type"
                                        + " for all rows at column 1.\n"
                                        + "Could not find a common super type for types: "
                                        + "[ROW<`f0` INT NOT NULL, `f1` TIME(0) NOT NULL> NOT NULL,"
                                        + " ROW<`f0` DOUBLE NOT NULL, `f1` DATE NOT NULL> NOT NULL]"),
                TestSpec.test("Cannot cast to the requested type")
                        .values(
                                DataTypes.ROW(
                                        DataTypes.FIELD("a", DataTypes.BIGINT()),
                                        DataTypes.FIELD("b", DataTypes.BINARY(3))),
                                row(valueLiteral(1), valueLiteral(LocalTime.of(1, 1))),
                                row(valueLiteral((short) 2), valueLiteral(LocalDate.of(1, 1, 1))))
                        .expectValidationException(
                                "Could not cast the value of the 1 column: [ 01:01 ] of a row: [ 1, 01:01 ]"
                                        + " to the requested type: BINARY(3)"),
                TestSpec.test("Cannot cast to the requested type in a nested row")
                        .values(
                                DataTypes.ROW(
                                        DataTypes.FIELD("a", DataTypes.BIGINT()),
                                        DataTypes.FIELD(
                                                "b",
                                                DataTypes.ROW(
                                                        DataTypes.FIELD(
                                                                "c", DataTypes.BINARY(3))))),
                                row(valueLiteral(1), row(valueLiteral(LocalTime.of(1, 1)))),
                                row(
                                        valueLiteral((short) 2),
                                        row(valueLiteral(LocalDate.of(1, 1, 1)))))
                        .expectValidationException(
                                "Could not cast the value of the 1 column: [ row(01:01) ] of a row: [ 1, row(01:01) ]"
                                        + " to the requested type: ROW<`c` BINARY(3)>"));
    }

    /** A simple function that returns a ROW. */
    @FunctionHint(output = @DataTypeHint("ROW<f0 INT, f1 STRING>"))
    public static class RowScalarFunction extends ScalarFunction {
        public Row eval() {
            return Row.of(1, "ABC");
        }

        @Override
        public int hashCode() {
            return 0;
        }

        @Override
        public boolean equals(Object obj) {
            return obj instanceof RowScalarFunction;
        }
    }

    /** A simple function that returns an int. */
    public static class IntScalarFunction extends ScalarFunction {
        public Integer eval() {
            return 1;
        }

        @Override
        public int hashCode() {
            return 0;
        }

        @Override
        public boolean equals(Object obj) {
            return obj instanceof IntScalarFunction;
        }
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("parameters")
    public void testValues(TestSpec testSpec) {
        if (testSpec.exceptionMessage != null) {
            if (testSpec.expectedRowType != null) {
                assertThatThrownBy(
                                () ->
                                        testSpec.getTreeBuilder()
                                                .values(
                                                        testSpec.expectedRowType,
                                                        testSpec.expressions))
                        .isInstanceOf(ValidationException.class)
                        .hasMessage(testSpec.exceptionMessage);
            } else {
                assertThatThrownBy(() -> testSpec.getTreeBuilder().values(testSpec.expressions))
                        .isInstanceOf(ValidationException.class)
                        .hasMessage(testSpec.exceptionMessage);
            }
            return;
        }

        ValuesQueryOperation operation;
        if (testSpec.expectedRowType != null) {
            operation =
                    (ValuesQueryOperation)
                            testSpec.getTreeBuilder()
                                    .values(testSpec.expectedRowType, testSpec.expressions);
        } else {
            operation =
                    (ValuesQueryOperation) testSpec.getTreeBuilder().values(testSpec.expressions);
        }

        if (testSpec.queryOperation != null) {
            assertThat(operation.getResolvedSchema())
                    .isEqualTo(testSpec.queryOperation.getResolvedSchema());
            assertThat(operation.getValues()).isEqualTo(testSpec.queryOperation.getValues());
        }
    }

    private static ResolvedExpression rowCtor(DataType dataType, ResolvedExpression... expression) {
        return CallExpression.permanent(
                BuiltInFunctionDefinitions.ROW, Arrays.asList(expression), dataType);
    }

    private static ResolvedExpression cast(ResolvedExpression expression, DataType dataType) {
        return CallExpression.permanent(
                BuiltInFunctionDefinitions.CAST,
                Arrays.asList(expression, typeLiteral(dataType)),
                dataType);
    }

    private static class TestSpec {
        private final String description;
        private Expression[] expressions;
        private @Nullable ValuesQueryOperation queryOperation;
        private @Nullable DataType expectedRowType;
        private @Nullable String exceptionMessage;

        private TestSpec(String description) {
            this.description = description;
        }

        public static TestSpec test(String description) {
            return new TestSpec(description);
        }

        public TestSpec values(Expression... expressions) {
            this.expressions = expressions;
            return this;
        }

        public TestSpec values(DataType rowType, Expression... expressions) {
            this.expressions = expressions;
            this.expectedRowType = rowType;
            return this;
        }

        public TestSpec equalTo(ValuesQueryOperation queryOperation) {
            this.queryOperation = queryOperation;
            return this;
        }

        public TestSpec expectValidationException(String message) {
            this.exceptionMessage = message;
            return this;
        }

        public OperationTreeBuilder getTreeBuilder() {
            return OperationTreeBuilder.create(
                    TableConfig.getDefault(),
                    new FunctionLookupMock(Collections.emptyMap()),
                    new DataTypeFactoryMock(),
                    name -> Optional.empty(), // do not support
                    (sqlExpression, inputRowType, outputType) -> {
                        throw new UnsupportedOperationException();
                    },
                    true);
        }

        @Override
        public String toString() {
            return description;
        }
    }
}
