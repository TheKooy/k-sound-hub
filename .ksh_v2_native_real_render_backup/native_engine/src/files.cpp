#include "files.hpp"

#include <fstream>
#include <sstream>

namespace ksound::native {

std::string read_text_file(const std::filesystem::path& path) {
    std::ifstream in(path);
    if (!in) {
        return {};
    }
    std::ostringstream buffer;
    buffer << in.rdbuf();
    return buffer.str();
}

void write_text_file(const std::filesystem::path& path, const std::string& text) {
    std::filesystem::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::trunc);
    out << text;
}

std::filesystem::file_time_type safe_last_write_time(const std::filesystem::path& path) {
    std::error_code ec;
    auto t = std::filesystem::last_write_time(path, ec);
    if (ec) {
        return {};
    }
    return t;
}

} // namespace ksound::native
