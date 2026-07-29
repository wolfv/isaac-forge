cmake_minimum_required(VERSION 3.16)
project(vpi_find_package_test C)

# This mirrors exactly what isaac_ros_common and isaac_ros_nitros do:
#   find_package(vpi REQUIRED)
#   target_link_libraries(... vpi)
# If this configure step fails, the whole Isaac ROS stack fails to build.
find_package(vpi REQUIRED)

if(NOT TARGET vpi)
  message(FATAL_ERROR "find_package(vpi) succeeded but did not define the 'vpi' target")
endif()

get_target_property(_vpi_loc vpi IMPORTED_LOCATION)
if(NOT EXISTS "${_vpi_loc}")
  message(FATAL_ERROR "vpi IMPORTED_LOCATION does not exist: ${_vpi_loc}")
endif()

get_target_property(_vpi_inc vpi INTERFACE_INCLUDE_DIRECTORIES)
if(NOT EXISTS "${_vpi_inc}/vpi/VPI.h")
  message(FATAL_ERROR "vpi include dir does not contain vpi/VPI.h: ${_vpi_inc}")
endif()

message(STATUS "VPI ${VPI_VERSION} found: ${_vpi_loc}")
