// E2E test: no argument provided
// Verifies that running wc-tool without a file argument produces an error to stderr
// and a non-zero exit code.

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>

static int run_command(const std::string& cmd) {
    return std::system(cmd.c_str());
}

static std::string capture_stderr(const std::string& cmd) {
    std::string capture_cmd = cmd + " 2>/tmp/wc_tool_stderr.txt";
    run_command(capture_cmd);
    std::ifstream f("/tmp/wc_tool_stderr.txt");
    std::string result((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    f.close();
    return result;
}

int main() {
    // Scenario: no argument — should fail with non-zero exit
    std::string cmd = "./build/wc-tool";
    int exit_code = run_command(cmd);
    assert(exit_code != 0); // Must return non-zero

    // Verify stderr contains an error message
    std::string stderr_output = capture_stderr(cmd);
    assert(stderr_output.length() > 0);

    return 0;
}
