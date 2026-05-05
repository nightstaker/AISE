/**
 * Integration scenario test: e2e_file_not_found
 *
 * End-to-end test: run wc-tool with a non-existent file,
 * verify it outputs error info to stderr and returns non-zero exit code.
 */

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>

static int run_command(const std::string& cmd) {
    return std::system(cmd.c_str());
}

static std::string capture_stderr(const std::string& cmd) {
    // Redirect stderr to a temp file
    std::string capture_cmd = cmd + " 2>/tmp/wc_scenario_stderr.txt";
    run_command(capture_cmd);
    std::ifstream f("/tmp/wc_scenario_stderr.txt");
    std::string result((std::istreambuf_iterator<char>(f)),
                        std::istreambuf_iterator<char>());
    f.close();
    return result;
}

int main() {
    // ---- Scenario: non-existent file ----
    std::string cmd = "./wc-tool /tmp/nonexistent_file_xyz_123.txt";
    int exit_code = run_command(cmd);
    assert(exit_code != 0); // Must return non-zero exit code

    // Verify stderr contains an error message
    std::string stderr_output = capture_stderr(cmd);
    assert(stderr_output.length() > 0); // Must produce error message on stderr

    // Verify the error message mentions the file not being found
    assert(stderr_output.find("nonexistent") != std::string::npos ||
           stderr_output.find("No such file") != std::string::npos ||
           stderr_output.find("cannot open") != std::string::npos ||
           stderr_output.find("Error") != std::string::npos ||
           stderr_output.find("error") != std::string::npos);

    return 0;
}
