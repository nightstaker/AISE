// E2E test: normal file processing
// Creates a file with known content and verifies the output format and counts.

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>

static void create_temp_file(const std::string& filename, const std::string& content) {
    std::ofstream f(filename);
    f << content;
    f.close();
}

static std::string capture_output(const std::string& cmd) {
    std::string capture_cmd = cmd + " > /tmp/wc_tool_output.txt 2>&1";
    std::system(capture_cmd.c_str());
    std::ifstream f("/tmp/wc_tool_output.txt");
    std::string result((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    f.close();
    return result;
}

int main() {
    // Scenario: normal file — "hello world\nfoo bar baz\n"
    // 2 lines, 5 words, 24 bytes
    create_temp_file("/tmp/test_e2e_normal.txt", "hello world\nfoo bar baz\n");
    std::string cmd = "./wc-tool /tmp/test_e2e_normal.txt";
    std::string output = capture_output(cmd);

    // Verify output contains expected values
    assert(output.find("2") != std::string::npos); // 2 lines
    assert(output.find("5") != std::string::npos); // 5 words
    assert(output.find("24") != std::string::npos); // 24 bytes
    assert(output.find("/tmp/test_e2e_normal.txt") != std::string::npos);

    return 0;
}
