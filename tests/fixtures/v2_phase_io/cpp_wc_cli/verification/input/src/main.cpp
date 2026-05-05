// wc-tool — a command-line word count utility.
// Usage: wc-tool <file>
// Output: <lines> <words> <bytes> <filename>

#include <iostream>
#include <fstream>
#include <string>
#include <sstream>
#include "input/arg_parser.h"
#include "input/file_opener.h"
#include "counter/combined_counter.h"
#include "output/formatter.h"

int main(int argc, char* argv[]) {
    try {
        // 1. Parse and validate arguments
        std::string filepath = input::parse_file_argument(argc, argv);

        // 2. Open the file
        auto file_result = input::open_file(filepath);
        if (!file_result.ok) {
            std::cerr << file_result.error_message << std::endl;
            return 1;
        }

        // 3. Read file content into a string (single read)
        std::ostringstream content_stream;
        content_stream << file_result.stream.rdbuf();
        std::string content = content_stream.str();

        // 4. Count lines, words, and bytes in a single pass
        auto stats = counter::count_all(content);
        if (!stats.ok) {
            std::cerr << "Error computing statistics" << std::endl;
            return 1;
        }

        // 5. Format and print results
        std::string output = output::format_output(
            stats.line_count,
            stats.word_count,
            stats.byte_count,
            filepath
        );
        std::cout << output << std::endl;

        return 0;
    } catch (const std::runtime_error& e) {
        std::cerr << e.what() << std::endl;
        return 1;
    }
}
