/**
 * Integration scenario test: line_counter
 *
 * Exercises the line counter through its public API,
 * covering happy paths, error conditions, and edge cases.
 */

#include "counter/line_counter.h"
#include <cassert>
#include <string>

int main() {
    // ---- Happy path: empty content ----
    {
        auto result = counter::count_lines("");
        assert(result.ok);
        assert(result.line_count == 0);
    }

    // ---- Happy path: single line without trailing newline ----
    {
        auto result = counter::count_lines("hello");
        assert(result.ok);
        assert(result.line_count == 0);
    }

    // ---- Happy path: single line with trailing newline ----
    {
        auto result = counter::count_lines("hello\n");
        assert(result.ok);
        assert(result.line_count == 1);
    }

    // ---- Happy path: multiple lines with trailing newline ----
    {
        auto result = counter::count_lines("line1\nline2\nline3\n");
        assert(result.ok);
        assert(result.line_count == 3);
    }

    // ---- Happy path: multiple lines without trailing newline ----
    {
        auto result = counter::count_lines("line1\nline2\nline3");
        assert(result.ok);
        assert(result.line_count == 2);
    }

    // ---- Happy path: single newline only ----
    {
        auto result = counter::count_lines("\n");
        assert(result.ok);
        assert(result.line_count == 1);
    }

    // ---- Happy path: multiple consecutive newlines ----
    {
        auto result = counter::count_lines("\n\n\n");
        assert(result.ok);
        assert(result.line_count == 3);
    }

    // ---- Happy path: empty lines mixed ----
    {
        auto result = counter::count_lines("\nhello\n\nworld\n");
        assert(result.ok);
        assert(result.line_count == 4);
    }

    // ---- Happy path: only whitespace, no newlines ----
    {
        auto result = counter::count_lines("   ");
        assert(result.ok);
        assert(result.line_count == 0);
    }

    // ---- Edge: very large content ----
    {
        std::string large(10000, 'a');
        large += '\n';
        auto result = counter::count_lines(large);
        assert(result.ok);
        assert(result.line_count == 1);
    }

    // ---- Edge: large content with many lines ----
    {
        std::string large;
        for (int i = 0; i < 1000; ++i) {
            large += "line\n";
        }
        auto result = counter::count_lines(large);
        assert(result.ok);
        assert(result.line_count == 1000);
    }

    // ---- Multi-call consistency ----
    {
        std::string content = "a\nb\nc\n";
        auto r1 = counter::count_lines(content);
        auto r2 = counter::count_lines(content);
        assert(r1.line_count == r2.line_count);
        assert(r1.line_count == 3);
    }

    return 0;
}
