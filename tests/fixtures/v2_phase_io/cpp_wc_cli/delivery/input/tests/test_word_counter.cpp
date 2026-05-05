#include "counter/word_counter.h"
#include <cassert>
#include <string>

int main() {
    // --- Happy path: empty content ---
    {
        auto result = counter::count_words("");
        assert(result.ok);
        assert(result.word_count == 0);
    }

    // --- Happy path: single word ---
    {
        auto result = counter::count_words("hello");
        assert(result.ok);
        assert(result.word_count == 1);
    }

    // --- Happy path: multiple words ---
    {
        auto result = counter::count_words("hello world");
        assert(result.ok);
        assert(result.word_count == 2);
    }

    // --- Happy path: multiple words with extra spaces ---
    {
        auto result = counter::count_words("  hello   world  ");
        assert(result.ok);
        assert(result.word_count == 2);
    }

    // --- Happy path: words with newlines ---
    {
        auto result = counter::count_words("one\ntwo\nthree\n");
        assert(result.ok);
        assert(result.word_count == 3);
    }

    // --- Happy path: tabs as separators ---
    {
        auto result = counter::count_words("a\tb\tc");
        assert(result.ok);
        assert(result.word_count == 3);
    }

    // --- Happy path: mixed whitespace ---
    {
        auto result = counter::count_words("  \n\t  hello\t world\n");
        assert(result.ok);
        assert(result.word_count == 2);
    }

    // --- Happy path: only whitespace ---
    {
        auto result = counter::count_words("   \n\t  ");
        assert(result.ok);
        assert(result.word_count == 0);
    }

    // --- Happy path: single character words ---
    {
        auto result = counter::count_words("a b c d e");
        assert(result.ok);
        assert(result.word_count == 5);
    }

    // --- Edge: large content ---
    {
        std::string large;
        for (int i = 0; i < 1000; ++i) {
            large += "word ";
        }
        auto result = counter::count_words(large);
        assert(result.ok);
        assert(result.word_count == 1000);
    }

    return 0;
}
