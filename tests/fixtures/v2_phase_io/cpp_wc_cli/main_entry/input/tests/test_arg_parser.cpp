#include <cassert>
#include <string>
#include <stdexcept>
#include "input/arg_parser.h"

int main() {
    // --- Happy path: exactly one argument ---
    {
        char buf[] = "myfile.txt";
        char* argv[] = {buf, buf}; // argv[0] = program, argv[1] = file
        std::string result = input::parse_file_argument(2, argv);
        assert(result == "myfile.txt");
    }

    // --- Happy path: file path with directory ---
    {
        char buf[] = "/home/user/document.txt";
        char* argv[] = {buf, buf};
        std::string result = input::parse_file_argument(2, argv);
        assert(result == "/home/user/document.txt");
    }

    // --- Happy path: file path with spaces ---
    {
        char buf[] = "my file.txt";
        char* argv[] = {buf, buf};
        std::string result = input::parse_file_argument(2, argv);
        assert(result == "my file.txt");
    }

    // --- Error: no arguments (only program name) ---
    {
        char buf[] = "wc-tool";
        char* argv[] = {buf};
        try {
            input::parse_file_argument(1, argv);
            assert(false && "Should have thrown");
        } catch (const std::runtime_error& e) {
            assert(std::string(e.what()).find("Usage") != std::string::npos);
        }
    }

    // --- Error: too many arguments ---
    {
        char buf1[] = "file1.txt";
        char buf2[] = "file2.txt";
        char buf3[] = "wc-tool";
        char* argv[] = {buf3, buf1, buf2};
        try {
            input::parse_file_argument(3, argv);
            assert(false && "Should have thrown");
        } catch (const std::runtime_error& e) {
            assert(std::string(e.what()).find("Usage") != std::string::npos);
        }
    }

    // --- Edge: empty filename ---
    {
        char buf[] = "";
        char* argv[] = {buf, buf};
        try {
            input::parse_file_argument(2, argv);
            assert(false && "Should have thrown");
        } catch (const std::runtime_error& e) {
            assert(std::string(e.what()).find("empty") != std::string::npos);
        }
    }

    return 0;
}
