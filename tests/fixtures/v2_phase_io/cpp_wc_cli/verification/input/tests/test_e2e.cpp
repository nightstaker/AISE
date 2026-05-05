// E2E test executable — tests end-to-end scenarios via system() calls to the wc-tool binary.
// Each scenario internally creates temporary files, runs the binary, and verifies output.

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <sstream>
#include <fstream>

// Helper: create a temporary file with given content
static void create_temp_file(const std::string& filename, const std::string& content) {
    std::ofstream f(filename);
    f << content;
    f.close();
}

// Helper: run a command and capture exit code
static int run_command(const std::string& cmd) {
    return std::system(cmd.c_str());
}

// Helper: read stdout from a command (using a temp file)
static std::string capture_output(const std::string& cmd) {
    std::string capture_cmd = cmd + " > /tmp/wc_tool_output.txt 2>&1";
    run_command(capture_cmd);
    std::ifstream f("/tmp/wc_tool_output.txt");
    std::string result((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    f.close();
    return result;
}

int main() {
    // === Scenario 1: e2e_normal_file ===
    // Create a file with known content and verify output
    {
        create_temp_file("/tmp/test_normal.txt", "hello world\nfoo bar baz\n");
        // Expected: 2 lines, 5 words, 19 bytes (hello world\nfoo bar baz\n = 19 bytes)
        // Actually: "hello world\nfoo bar baz\n" = 24 bytes
        // Let me count: h-e-l-l-o- -w-o-r-l-d-\n = 12, f-o-o- -b-a-r- -b-a-z-\n = 12, total = 24
        // Wait: "hello world\nfoo bar baz\n"
        // h(1)e(2)l(3)l(4)o(5) (6)w(7)o(8)r(9)l(10)d(11)\n(12)f(13)o(14)o(15) (16)b(17)a(18)r(19) (20)b(21)a(22)z(23)\n(24)
        // So 24 bytes, 2 lines, 5 words
        std::string cmd = "./build/wc-tool /tmp/test_normal.txt";
        std::string output = capture_output(cmd);
        assert(output.find("2") != std::string::npos);
        assert(output.find("5") != std::string::npos);
        assert(output.find("24") != std::string::npos);
        assert(output.find("/tmp/test_normal.txt") != std::string::npos);
    }

    // === Scenario 2: e2e_empty_file ===
    {
        create_temp_file("/tmp/test_empty.txt", "");
        std::string cmd = "./build/wc-tool /tmp/test_empty.txt";
        std::string output = capture_output(cmd);
        assert(output.find("0") != std::string::npos);
        assert(output.find("/tmp/test_empty.txt") != std::string::npos);
    }

    // === Scenario 3: e2e_no_argument ===
    {
        std::string cmd = "./build/wc-tool 2>/tmp/wc_tool_stderr.txt";
        int exit_code = run_command(cmd);
        assert(exit_code != 0); // Should return non-zero
    }

    // === Scenario 4: e2e_file_not_found ===
    {
        std::string cmd = "./build/wc-tool /tmp/nonexistent_file_xyz.txt 2>/tmp/wc_tool_stderr.txt";
        int exit_code = run_command(cmd);
        assert(exit_code != 0); // Should return non-zero
    }

    // === Scenario 5: e2e_no_trailing_newline ===
    {
        create_temp_file("/tmp/test_no_newline.txt", "hello world");
        // "hello world" = 11 bytes, 1 line (no trailing newline but counts as 1), 2 words
        std::string cmd = "./build/wc-tool /tmp/test_no_newline.txt";
        std::string output = capture_output(cmd);
        assert(output.find("1") != std::string::npos); // 1 line
        assert(output.find("2") != std::string::npos); // 2 words
        assert(output.find("11") != std::string::npos); // 11 bytes
        assert(output.find("/tmp/test_no_newline.txt") != std::string::npos);
    }

    return 0;
}
