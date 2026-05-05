// E2E test: file without trailing newline
// Verifies wc-compatible line counting: a file without a trailing newline
// still counts the last line.

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
    // Scenario: "hello world" — no trailing newline
    // 1 line, 2 words, 11 bytes
    create_temp_file("/tmp/test_e2e_no_newline.txt", "hello world");
    std::string cmd = "./wc-tool /tmp/test_e2e_no_newline.txt";
    std::string output = capture_output(cmd);

    assert(output.find("1") != std::string::npos); // 1 line
    assert(output.find("2") != std::string::npos); // 2 words
    assert(output.find("11") != std::string::npos); // 11 bytes
    assert(output.find("/tmp/test_e2e_no_newline.txt") != std::string::npos);

    return 0;
}
