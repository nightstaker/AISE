/**
 * Integration scenario test: byte_counter
 *
 * Exercises the byte counter through its public API,
 * covering happy paths, error conditions, and edge cases.
 */

#include "counter/byte_counter.h"
#include <cassert>
#include <string>

int main() {
    // ---- Happy path: empty string ----
    {
        auto result = counter::count_bytes("");
        assert(result.ok);
        assert(result.byte_count == 0);
    }

    // ---- Happy path: single byte ----
    {
        auto result = counter::count_bytes("a");
        assert(result.ok);
        assert(result.byte_count == 1);
    }

    // ---- Happy path: multiple bytes ----
    {
        auto result = counter::count_bytes("hello world");
        assert(result.ok);
        assert(result.byte_count == 11);
    }

    // ---- Happy path: with newline characters ----
    {
        auto result = counter::count_bytes("a\nb\n");
        assert(result.ok);
        assert(result.byte_count == 4);
    }

    // ---- Happy path: only whitespace ----
    {
        auto result = counter::count_bytes("   \t\n");
        assert(result.ok);
        assert(result.byte_count == 5);
    }

    // ---- Happy path: ASCII printable characters ----
    {
        auto result = counter::count_bytes("!@#$%");
        assert(result.ok);
        assert(result.byte_count == 5);
    }

    // ---- Edge: large content ----
    {
        std::string s(10000, 'x');
        auto result = counter::count_bytes(s);
        assert(result.ok);
        assert(result.byte_count == 10000);
    }

    // ---- Edge: string with null character embedded ----
    {
        std::string s(3, '\0');
        auto result = counter::count_bytes(s);
        assert(result.ok);
        assert(result.byte_count == 3);
    }

    // ---- Multi-call consistency ----
    {
        std::string content = "hello world\n";
        auto r1 = counter::count_bytes(content);
        auto r2 = counter::count_bytes(content);
        assert(r1.byte_count == r2.byte_count);
        assert(r1.byte_count == 12);
    }

    return 0;
}
