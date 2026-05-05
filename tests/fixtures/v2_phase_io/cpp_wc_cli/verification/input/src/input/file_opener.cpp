#include "input/file_opener.h"
#include <fstream>
#include <string>

namespace input {

/**
 * Open a file for reading.
 *
 * @param filename  Path to the file to open
 * @return          Result struct with ok flag, ifstream, and optional error message
 */
FileOpenResult open_file(const std::string& filename) {
    FileOpenResult result;
    result.ok = false;
    result.error_message.clear();

    if (filename.empty()) {
        result.error_message = "Error: empty filename";
        return result;
    }

    result.stream.open(filename, std::ios::in);
    if (!result.stream.is_open()) {
        result.error_message = "Error: cannot open file '" + filename + "'";
        return result;
    }

    result.ok = true;
    return result;
}

} // namespace input
