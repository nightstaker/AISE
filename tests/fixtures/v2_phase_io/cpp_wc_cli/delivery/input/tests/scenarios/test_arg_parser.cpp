/**
 * Integration scenario test: arg_parser
 *
 * Exercises the argument parser through its public API,
 * covering happy paths, error conditions, and edge cases.
 */

#include "input/arg_parser.h"
#include <cassert>
#include <cstring>
#include <string>

int main() {
    // ---- Happy path: single valid file argument ----
    {
        char buf[] = "myfile.txt";
        char* argv[] = {buf, buf};
        std::string result = input::parse_file_argument(2, argv);
        assert(result == "myfile.txt");
    }

    // ---- Happy path: absolute path ----
    {
        char buf[] = "/usr/local/bin/data.txt";
        char* argv[] = {buf, buf};
        std::string result = input::parse_file_argument(2, argv);
        assert(result == "/usr/local/bin/data.txt");
    }

    // ---- Happy path: relative path with directory ----
    {
        char buf[] = "./data/input.csv";
        char* argv[] = {buf, buf};
        std::string result = input::parse_file_argument(2, argv);
        assert(result == "./data/input.csv");
    }

    // ---- Happy path: filename with spaces ----
    {
        char buf[] = "my report.txt";
        char* argv[] = {buf, buf};
        std::string result = input::parse_file_argument(2, argv);
        assert(result == "my report.txt");
    }

    // ---- Happy path: filename with dots ----
    {
        char buf[] = "archive.tar.gz";
        char* argv[] = {buf, buf};
        std::string result = input::parse_file_argument(2, argv);
        assert(result == "archive.tar.gz");
    }

    // ---- Error: no arguments (only program name) ----
    {
        char buf[] = "wc-tool";
        char* argv[] = {buf};
        bool caught = false;
        try {
            input::parse_file_argument(1, argv);
        } catch (const std::exception& ex) {
            caught = true;
            std::string msg = ex.what();
            assert(msg.find("Usage") != std::string::npos);
        }
        assert(caught);
    }

    // ---- Error: too many arguments ----
    {
        char f1[] = "file1.txt";
        char f2[] = "file2.txt";
        char prog[] = "wc-tool";
        char* argv[] = {prog, f1, f2};
        bool caught = false;
        try {
            input::parse_file_argument(3, argv);
        } catch (const std::exception& ex) {
            caught = true;
            std::string msg = ex.what();
            assert(msg.find("Usage") != std::string::npos);
        }
        assert(caught);
    }

    // ---- Error: empty filename ----
    {
        char buf[] = "";
        char* argv[] = {buf, buf};
        bool caught = false;
        try {
            input::parse_file_argument(2, argv);
        } catch (const std::exception& ex) {
            caught = true;
            std::string msg = ex.what();
            assert(msg.find("empty") != std::string::npos);
        }
        assert(caught);
    }

    // ---- Multi-call consistency: valid arguments only ----
    {
        const char* filenames[] = {"a.txt", "b.log", "c.dat"};
        for (int i = 0; i < 3; ++i) {
            char* buf = new char[16];
            const char* fname = filenames[i];
            for (size_t j = 0; j < strlen(fname); ++j) {
                buf[j] = fname[j];
            }
            buf[strlen(fname)] = '\0';
            char* argv[] = {buf, buf};
            std::string result = input::parse_file_argument(2, argv);
            assert(result == fname);
            delete[] buf;
        }
    }

    return 0;
}
