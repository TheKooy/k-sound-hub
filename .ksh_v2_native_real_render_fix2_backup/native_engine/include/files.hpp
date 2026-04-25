#pragma once

#include <filesystem>
#include <string>

namespace ksound::native {

std::string read_text_file(const std::filesystem::path& path);
void write_text_file(const std::filesystem::path& path, const std::string& text);
std::filesystem::file_time_type safe_last_write_time(const std::filesystem::path& path);

} // namespace ksound::native
