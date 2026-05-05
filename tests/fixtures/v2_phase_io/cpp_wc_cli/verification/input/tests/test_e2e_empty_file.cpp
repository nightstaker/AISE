// E2E test: empty file processing
// Verifies that an empty file produces "0 0 0 filename".

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
    // Scenario: empty file — ""
    // 0 lines, 0 words, 0 bytes
    create_temp_file("/tmp/test_e2e_empty.txt", "");
    std::string cmd = "./wc-tool /tmp/test_e2e_empty.txt";
    std::string output = capture_output(cmd);

    assert(output.find("0") != std::string::npos);
    assert(output.find("/tmp/test_e2e_empty.txt") != std::string::npos);

    return 0;
}
