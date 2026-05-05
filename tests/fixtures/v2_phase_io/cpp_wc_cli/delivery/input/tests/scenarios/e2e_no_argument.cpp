/**
 * Integration scenario test: e2e_no_argument
 *
 * End-to-end test: run wc-tool without any file argument,
 * verify it outputs an error to stderr and returns non-zero exit code.
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
    std::string capture_cmd = cmd + " 2>/tmp/wc_scenario_stderr.txt";
    run_command(capture_cmd);
    std::ifstream f("/tmp/wc_scenario_stderr.txt");
    std::string result((std::istreambuf_iterator<char>(f)),
                        std::istreambuf_iterator<char>());
    f.close();
    return result;
}

int main() {
    // ---- Scenario 1: no arguments at all ----
    std::string cmd1 = "./wc-tool";
    int exit_code1 = run_command(cmd1);
    assert(exit_code1 != 0); // Must return non-zero exit code

    std::string stderr1 = capture_stderr(cmd1);
    assert(stderr1.length() > 0); // Must produce error message on stderr

    // ---- Scenario 2: only program name (argv[0]) ----
    // Same as Scenario 1 in practice since the shell strips it
    int exit_code2 = run_command(cmd1);
    assert(exit_code2 != 0);

    // ---- Scenario 3: verify stderr contains helpful message ----
    assert(stderr1.find("Usage") != std::string::npos ||
           stderr1.find("usage") != std::string::npos ||
           stderr1.find("error") != std::string::npos ||
           stderr1.find("Error") != std::string::npos);

    return 0;
}
