/**
 * Integration scenario test: output_formatter
 *
 * Exercises the output formatter through its public API,
 * covering happy paths, edge cases, and output format validation.
 */

#include "output/formatter.h"
#include <cassert>
#include <string>

int main() {
    // ---- Happy path: basic formatting ----
    {
        std::string output = output::format_output(10, 50, 200, "myfile.txt");
        assert(output == "10 50 200 myfile.txt");
    }

    // ---- Happy path: zero counts ----
    {
        std::string output = output::format_output(0, 0, 0, "empty.txt");
        assert(output == "0 0 0 empty.txt");
    }

    // ---- Happy path: single values ----
    {
        std::string output = output::format_output(1, 1, 1, "a.txt");
        assert(output == "1 1 1 a.txt");
    }

    // ---- Happy path: large values ----
    {
        std::string output = output::format_output(999999, 5000000, 10000000, "big.txt");
        assert(output == "999999 5000000 10000000 big.txt");
    }

    // ---- Happy path: filename with path ----
    {
        std::string output = output::format_output(1, 2, 3, "/path/to/file.txt");
        assert(output == "1 2 3 /path/to/file.txt");
    }

    // ---- Happy path: filename with spaces ----
    {
        std::string output = output::format_output(1, 2, 3, "my file.txt");
        assert(output == "1 2 3 my file.txt");
    }

    // ---- Edge: filename with special characters ----
    {
        std::string output = output::format_output(0, 0, 0, "file-with_special.chars");
        assert(output == "0 0 0 file-with_special.chars");
    }

    // ---- Edge: maximum int64_t values ----
    {
        std::string output = output::format_output(
            9223372036854775807LL,
            9223372036854775807LL,
            9223372036854775807LL,
            "max.txt"
        );
        assert(output.find("9223372036854775807") != std::string::npos);
        assert(output.find("max.txt") != std::string::npos);
    }

    // ---- Format validation: exactly 3 spaces as separators ----
    {
        std::string output = output::format_output(1, 2, 3, "test.txt");
        // Count spaces between numbers
        int space_count = 0;
        for (size_t i = 0; i < output.size(); ++i) {
            if (output[i] == ' ') {
                space_count++;
            }
        }
        assert(space_count == 3);
    }

    return 0;
}
