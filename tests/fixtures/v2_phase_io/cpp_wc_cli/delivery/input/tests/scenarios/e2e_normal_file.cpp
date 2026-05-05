/**
 * Integration scenario test: e2e_normal_file
 *
 * End-to-end test: run wc-tool on a file with known content,
 * verify the output format and counts are correct.
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
    // ---- Scenario 1: normal file with known content ----
    // "hello world\nfoo bar baz\n"
    // Expected: 2 lines, 5 words, 24 bytes
    create_temp_file("/tmp/wc_scenario_normal.txt", "hello world\nfoo bar baz\n");
    std::string cmd = "./wc-tool /tmp/wc_scenario_normal.txt";
    std::string output = capture_output(cmd);

    // Verify output contains expected values
    assert(output.find("2") != std::string::npos);  // 2 lines
    assert(output.find("5") != std::string::npos);  // 5 words
    assert(output.find("24") != std::string::npos); // 24 bytes
    assert(output.find("/tmp/wc_scenario_normal.txt") != std::string::npos);

    // ---- Scenario 2: file with multiple lines and words ----
    // "a b\nc d\ne f\n"
    // Expected: 3 lines, 6 words, 12 bytes
    create_temp_file("/tmp/wc_scenario_multi.txt", "a b\nc d\ne f\n");
    cmd = "./wc-tool /tmp/wc_scenario_multi.txt";
    output = capture_output(cmd);

    assert(output.find("3") != std::string::npos);  // 3 lines
    assert(output.find("6") != std::string::npos);  // 6 words
    assert(output.find("12") != std::string::npos); // 12 bytes
    assert(output.find("/tmp/wc_scenario_multi.txt") != std::string::npos);

    return 0;
}
