#include "counter/combined_counter.h"
#include <cassert>
#include <string>

int main() {
    // --- Happy path: empty content ---
    {
        auto result = counter::count_all("");
        assert(result.ok);
        assert(result.line_count == 0);
        assert(result.word_count == 0);
        assert(result.byte_count == 0);
    }

    // --- Happy path: single word, no newline ---
    {
        auto result = counter::count_all("hello");
        assert(result.ok);
        assert(result.line_count == 0);
        assert(result.word_count == 1);
        assert(result.byte_count == 5);
    }

    // --- Happy path: single word with trailing newline ---
    {
        auto result = counter::count_all("hello\n");
        assert(result.ok);
        assert(result.line_count == 1);
        assert(result.word_count == 1);
        assert(result.byte_count == 6);
    }

    // --- Happy path: multiple lines with trailing newline ---
    {
        auto result = counter::count_all("line1\nline2\nline3\n");
        assert(result.ok);
        assert(result.line_count == 3);
        assert(result.word_count == 3);
        assert(result.byte_count == 18);
    }

    // --- Happy path: multiple lines without trailing newline ---
    {
        auto result = counter::count_all("line1\nline2\nline3");
        assert(result.ok);
        assert(result.line_count == 2);
        assert(result.word_count == 3);
        assert(result.byte_count == 17);
    }

    // --- Happy path: multiple words per line ---
    {
        auto result = counter::count_all("hello world\nfoo bar\n");
        assert(result.ok);
        assert(result.line_count == 2);
        assert(result.word_count == 4);
        assert(result.byte_count == 20);
    }

    // --- Happy path: extra whitespace ---
    {
        auto result = counter::count_all("  hello   world  \n");
        assert(result.ok);
        assert(result.line_count == 1);
        assert(result.word_count == 2);
        assert(result.byte_count == 18);
    }

    // --- Happy path: tabs as separators ---
    {
        auto result = counter::count_all("a\tb\tc\n");
        assert(result.ok);
        assert(result.line_count == 1);
        assert(result.word_count == 3);
        assert(result.byte_count == 6);
    }

    // --- Happy path: only whitespace ---
    {
        auto result = counter::count_all("   \n\t  ");
        assert(result.ok);
        assert(result.line_count == 1);
        assert(result.word_count == 0);
        assert(result.byte_count == 7);
    }

    // --- Happy path: only newlines ---
    {
        auto result = counter::count_all("\n\n\n");
        assert(result.ok);
        assert(result.line_count == 3);
        assert(result.word_count == 0);
        assert(result.byte_count == 3);
    }

    // --- Happy path: mixed empty lines ---
    {
        auto result = counter::count_all("\nhello\n\nworld\n");
        assert(result.ok);
        assert(result.line_count == 4);
        assert(result.word_count == 2);
        assert(result.byte_count == 14);
    }

    // --- Happy path: single character words ---
    {
        auto result = counter::count_all("a b c d e");
        assert(result.ok);
        assert(result.line_count == 0);
        assert(result.word_count == 5);
        assert(result.byte_count == 9);
    }

    // --- Happy path: carriage return as whitespace ---
    {
        auto result = counter::count_all("hello\rworld\n");
        assert(result.ok);
        assert(result.line_count == 1);
        assert(result.word_count == 2);
        assert(result.byte_count == 12);
    }

    // --- Edge: very large content ---
    {
        std::string large(10000, 'a');
        large += '\n';
        auto result = counter::count_all(large);
        assert(result.ok);
        assert(result.line_count == 1);
        assert(result.word_count == 1);
        assert(result.byte_count == 10001);
    }

    return 0;
}
