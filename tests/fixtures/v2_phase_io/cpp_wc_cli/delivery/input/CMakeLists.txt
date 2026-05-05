cmake_minimum_required(VERSION 3.14)
project(wc-tool VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Static library — all subsystem source compiled once
add_library(wc-tool-lib
    src/input/arg_parser.cpp
    src/input/file_opener.cpp
    src/counter/line_counter.cpp
    src/counter/word_counter.cpp
    src/counter/byte_counter.cpp
    src/counter/combined_counter.cpp
    src/output/formatter.cpp
)
target_include_directories(wc-tool-lib PUBLIC src)

# Main executable
add_executable(wc-tool src/main.cpp)
target_link_libraries(wc-tool PRIVATE wc-tool-lib)

# Unit test executables — each links against the shared library
add_executable(test_line_counter tests/test_line_counter.cpp)
target_link_libraries(test_line_counter PRIVATE wc-tool-lib)

add_executable(test_word_counter tests/test_word_counter.cpp)
target_link_libraries(test_word_counter PRIVATE wc-tool-lib)

add_executable(test_byte_counter tests/test_byte_counter.cpp)
target_link_libraries(test_byte_counter PRIVATE wc-tool-lib)

add_executable(test_combined_counter tests/test_combined_counter.cpp)
target_link_libraries(test_combined_counter PRIVATE wc-tool-lib)

add_executable(test_arg_parser tests/test_arg_parser.cpp)
target_link_libraries(test_arg_parser PRIVATE wc-tool-lib)

add_executable(test_file_opener tests/test_file_opener.cpp)
target_link_libraries(test_file_opener PRIVATE wc-tool-lib)

add_executable(test_output_formatter tests/test_output_formatter.cpp)
target_link_libraries(test_output_formatter PRIVATE wc-tool-lib)

# E2E test executables — each links against the shared library
add_executable(test_e2e_normal_file tests/test_e2e_normal_file.cpp)
target_link_libraries(test_e2e_normal_file PRIVATE wc-tool-lib)

add_executable(test_e2e_empty_file tests/test_e2e_empty_file.cpp)
target_link_libraries(test_e2e_empty_file PRIVATE wc-tool-lib)

add_executable(test_e2e_no_argument tests/test_e2e_no_argument.cpp)
target_link_libraries(test_e2e_no_argument PRIVATE wc-tool-lib)

add_executable(test_e2e_file_not_found tests/test_e2e_file_not_found.cpp)
target_link_libraries(test_e2e_file_not_found PRIVATE wc-tool-lib)

add_executable(test_e2e_no_trailing_newline tests/test_e2e_no_trailing_newline.cpp)
target_link_libraries(test_e2e_no_trailing_newline PRIVATE wc-tool-lib)

# === Scenario integration tests (tests/scenarios/) ===
add_executable(scenario_line_counter tests/scenarios/test_line_counter.cpp)
target_link_libraries(scenario_line_counter PRIVATE wc-tool-lib)

add_executable(scenario_word_counter tests/scenarios/test_word_counter.cpp)
target_link_libraries(scenario_word_counter PRIVATE wc-tool-lib)

add_executable(scenario_byte_counter tests/scenarios/test_byte_counter.cpp)
target_link_libraries(scenario_byte_counter PRIVATE wc-tool-lib)

add_executable(scenario_arg_parser tests/scenarios/test_arg_parser.cpp)
target_link_libraries(scenario_arg_parser PRIVATE wc-tool-lib)

add_executable(scenario_output_formatter tests/scenarios/test_output_formatter.cpp)
target_link_libraries(scenario_output_formatter PRIVATE wc-tool-lib)

add_executable(scenario_e2e_normal_file tests/scenarios/e2e_normal_file.cpp)
target_link_libraries(scenario_e2e_normal_file PRIVATE wc-tool-lib)

add_executable(scenario_e2e_empty_file tests/scenarios/e2e_empty_file.cpp)
target_link_libraries(scenario_e2e_empty_file PRIVATE wc-tool-lib)

add_executable(scenario_e2e_no_argument tests/scenarios/e2e_no_argument.cpp)
target_link_libraries(scenario_e2e_no_argument PRIVATE wc-tool-lib)

add_executable(scenario_e2e_file_not_found tests/scenarios/e2e_file_not_found.cpp)
target_link_libraries(scenario_e2e_file_not_found PRIVATE wc-tool-lib)

add_executable(scenario_e2e_no_trailing_newline tests/scenarios/e2e_no_trailing_newline.cpp)
target_link_libraries(scenario_e2e_no_trailing_newline PRIVATE wc-tool-lib)

# Enable testing
enable_testing()

# Unit tests
add_test(NAME LineCounterTest COMMAND test_line_counter)
add_test(NAME WordCounterTest COMMAND test_word_counter)
add_test(NAME ByteCounterTest COMMAND test_byte_counter)
add_test(NAME CombinedCounterTest COMMAND test_combined_counter)
add_test(NAME ArgParserTest COMMAND test_arg_parser)
add_test(NAME OutputFormatterTest COMMAND test_output_formatter)
add_test(NAME FileOpenerTest COMMAND test_file_opener)

# E2E unit tests
add_test(NAME E2ENormalFileTest COMMAND test_e2e_normal_file)
add_test(NAME E2EEmptyFileTest COMMAND test_e2e_empty_file)
add_test(NAME E2ENoArgumentTest COMMAND test_e2e_no_argument)
add_test(NAME E2EFileNotFoundTest COMMAND test_e2e_file_not_found)
add_test(NAME E2ENoTrailingNewlineTest COMMAND test_e2e_no_trailing_newline)

# Scenario integration tests
add_test(NAME ScenarioLineCounterTest COMMAND scenario_line_counter)
add_test(NAME ScenarioWordCounterTest COMMAND scenario_word_counter)
add_test(NAME ScenarioByteCounterTest COMMAND scenario_byte_counter)
add_test(NAME ScenarioArgParserTest COMMAND scenario_arg_parser)
add_test(NAME ScenarioOutputFormatterTest COMMAND scenario_output_formatter)
add_test(NAME ScenarioE2ENormalFileTest COMMAND scenario_e2e_normal_file)
add_test(NAME ScenarioE2EEmptyFileTest COMMAND scenario_e2e_empty_file)
add_test(NAME ScenarioE2ENoArgumentTest COMMAND scenario_e2e_no_argument)
add_test(NAME ScenarioE2EFileNotFoundTest COMMAND scenario_e2e_file_not_found)
add_test(NAME ScenarioE2ENoTrailingNewlineTest COMMAND scenario_e2e_no_trailing_newline)
