/**
 * Integration scenario test: e2e_no_trailing_newline
 *
 * End-to-end test: run wc-tool on a file without a trailing newline,
 * verify wc-compatible line counting behavior.
 */

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
    std::string capture_cmd = cmd + " > /tmp/wc_scenario_output.txt 2>&1";
    std::system(capture_cmd.c_str());
    std::ifstream f("/tmp/wc_scenario_output.txt");
    std::string result((std::istreambuf_iterator<char>(f)),
                        std::istreambuf_iterator<char>());
    f.close();
    return result;
}

int main() {
    // ---- Scenario 1: single line without trailing newline ----
    // "hello world" = 11 bytes, no newline
    // Expected: 0 lines (no newline chars), 2 words, 11 bytes
    create_temp_file("/tmp/wc_scenario_no_nl.txt", "hello world");
    std::string cmd = "./wc-tool /tmp/wc_scenario_no_nl.txt";
    std::string output = capture_output(cmd);

    assert(output.find("2") != std::string::npos);  // 2 words
    assert(output.find("11") != std::string::npos); // 11 bytes
    assert(output.find("/tmp/wc_scenario_no_nl.txt") != std::string::npos);

    // ---- Scenario 2: multiple lines, last without trailing newline ----
    // "line1\nline2\nline3" = 17 bytes, 2 newlines
    // Expected: 2 lines, 3 words, 17 bytes
    create_temp_file("/tmp/wc_scenario_multi_nonl.txt", "line1\nline2\nline3");
    cmd = "./wc-tool /tmp/wc_scenario_multi_nonl.txt";
    output = capture_output(cmd);

    assert(output.find("2") != std::string::npos);  // 2 lines (newline count)
    assert(output.find("3") != std::string::npos);  // 3 words
    assert(output.find("17") != std::string::npos); // 17 bytes
    assert(output.find("/tmp/wc_scenario_multi_nonl.txt") != std::string::npos);

    return 0;
}
