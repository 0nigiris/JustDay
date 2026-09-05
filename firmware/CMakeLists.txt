# Прошивка аппаратного контроллера Remo32 для ESP32-S3.
#
# Собирается ESP-IDF 5.2+:
#   . ~/esp/esp-idf-525/export.sh
#   idf.py set-target esp32s3
#   idf.py build
cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(remo32_firmware)
