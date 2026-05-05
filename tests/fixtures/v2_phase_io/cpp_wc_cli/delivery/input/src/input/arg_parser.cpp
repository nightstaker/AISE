#include "input/arg_parser.h"
#include <cstdlib>
#include <string>
#include <stdexcept>

namespace input {

std::string parse_file_argument(int argc, char* argv[]) {
    if (argc != 2) {
        throw std::runtime_error("Usage: wc-tool <file>");
    }

    const char* file_arg = argv[1];
    if (file_arg == nullptr || file_arg[0] == '\0') {
        throw std::runtime_error("Error: empty filename");
    }

    return std::string(file_arg);
}

} // namespace input
