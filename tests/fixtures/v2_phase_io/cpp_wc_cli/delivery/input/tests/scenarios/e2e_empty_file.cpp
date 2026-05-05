/**
 * Integration scenario test: e2e_empty_file
 *
 * End-to-end test: run wc-tool on an empty file,
 * verify the output is "0 0 0 filename".
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
    // ---- Scenario: empty file ----
    // 0 lines, 0 words, 0 bytes
    create_temp_file("/tmp/wc_scenario_empty.txt", "");
    std::string cmd = "./wc-tool /tmp/wc_scenario_empty.txt";
    std::string output = capture_output(cmd);

    // Verify output format: "0 0 0 filename"
    assert(output.find("0 0 0") != std::string::npos);
    assert(output.find("/tmp/wc_scenario_empty.txt") != std::string::npos);

    // ---- Scenario: file with only whitespace ----
    // "   \n" = 3 bytes + 1 newline = 4 bytes, 1 line, 0 words
    create_temp_file("/tmp/wc_scenario_whitespace.txt", "   \n");
    cmd = "./wc-tool /tmp/wc_scenario_whitespace.txt";
    output = capture_output(cmd);

    assert(output.find("1") != std::string::npos);  // 1 line
    assert(output.find("0") != std::string::npos);  // 0 words
    assert(output.find("4") != std::string::npos);  // 4 bytes
    assert(output.find("/tmp/wc_scenario_whitespace.txt") != std::string::npos);

    return 0;
}
