#include "input/file_opener.h"
#include <cassert>
#include <cstdio>
#include <string>
#include <unistd.h>

static std::string create_temp_file(const std::string& content) {
    std::string path = "/tmp/test_wc_tool_XXXXXX";
    char buf[1024];
    snprintf(buf, sizeof(buf), "%s", path.c_str());
    int fd = mkstemp(buf);
    if (fd < 0) return "";
    write(fd, content.c_str(), content.size());
    close(fd);
    return buf;
}

int main() {
    // --- Happy path: valid file ---
    {
        std::string tmp = create_temp_file("hello\nworld\n");
        assert(!tmp.empty());
        auto result = input::open_file(tmp);
        assert(result.ok);
        char buf[256];
        result.stream.getline(buf, sizeof(buf));
        assert(result.stream);
        std::remove(tmp.c_str());
    }

    // --- Happy path: empty file ---
    {
        std::string tmp = create_temp_file("");
        assert(!tmp.empty());
        auto result = input::open_file(tmp);
        assert(result.ok);
        assert(!result.stream.eof());
        std::remove(tmp.c_str());
    }

    // --- Error: file does not exist ---
    {
        auto result = input::open_file("/nonexistent/path/file_does_not_exist.txt");
        assert(!result.ok);
        assert(!result.error_message.empty());
    }

    // --- Error: empty filename ---
    {
        auto result = input::open_file("");
        assert(!result.ok);
        assert(!result.error_message.empty());
    }

    return 0;
}
