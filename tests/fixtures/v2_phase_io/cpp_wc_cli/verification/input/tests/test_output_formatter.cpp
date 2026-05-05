#include "output/formatter.h"
#include <cassert>
#include <string>

int main() {
    // --- Happy path: basic formatting ---
    {
        std::string output = output::format_output(10, 50, 200, "myfile.txt");
        assert(output == "10 50 200 myfile.txt");
    }

    // --- Happy path: zero counts ---
    {
        std::string output = output::format_output(0, 0, 0, "empty.txt");
        assert(output == "0 0 0 empty.txt");
    }

    // --- Happy path: single values ---
    {
        std::string output = output::format_output(1, 1, 1, "a.txt");
        assert(output == "1 1 1 a.txt");
    }

    // --- Happy path: large values ---
    {
        std::string output = output::format_output(999999, 5000000, 10000000, "big.txt");
        assert(output == "999999 5000000 10000000 big.txt");
    }

    // --- Happy path: filename with path ---
    {
        std::string output = output::format_output(1, 2, 3, "/path/to/file.txt");
        assert(output == "1 2 3 /path/to/file.txt");
    }

    // --- Happy path: filename with spaces ---
    {
        std::string output = output::format_output(1, 2, 3, "my file.txt");
        assert(output == "1 2 3 my file.txt");
    }

    return 0;
}
