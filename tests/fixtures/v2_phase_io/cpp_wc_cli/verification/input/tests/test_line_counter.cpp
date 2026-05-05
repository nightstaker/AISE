#include "counter/line_counter.h"
#include <cassert>
#include <string>

int main() {
    // --- Happy path: empty content ---
    {
        auto result = counter::count_lines("");
        assert(result.ok);
        assert(result.line_count == 0);
    }

    // --- Happy path: single line without trailing newline ---
    {
        auto result = counter::count_lines("hello");
        assert(result.ok);
        assert(result.line_count == 0);
    }

    // --- Happy path: single line with trailing newline ---
    {
        auto result = counter::count_lines("hello\n");
        assert(result.ok);
        assert(result.line_count == 1);
    }

    // --- Happy path: multiple lines with trailing newline ---
    {
        auto result = counter::count_lines("line1\nline2\nline3\n");
        assert(result.ok);
        assert(result.line_count == 3);
    }

    // --- Happy path: multiple lines without trailing newline ---
    {
        auto result = counter::count_lines("line1\nline2\nline3");
        assert(result.ok);
        assert(result.line_count == 2);
    }

    // --- Happy path: single newline only ---
    {
        auto result = counter::count_lines("\n");
        assert(result.ok);
        assert(result.line_count == 1);
    }

    // --- Happy path: multiple consecutive newlines ---
    {
        auto result = counter::count_lines("\n\n\n");
        assert(result.ok);
        assert(result.line_count == 3);
    }

    // --- Happy path: empty lines mixed ---
    {
        auto result = counter::count_lines("\nhello\n\nworld\n");
        assert(result.ok);
        assert(result.line_count == 4);
    }

    // --- Edge: very large content ---
    {
        std::string large(10000, 'a');
        large += '\n';
        auto result = counter::count_lines(large);
        assert(result.ok);
        assert(result.line_count == 1);
    }

    return 0;
}
