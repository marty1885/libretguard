cmake_minimum_required(VERSION 3.20)
project(retguard LANGUAGES C CXX ASM)
include(GNUInstallDirs)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64)$")
  message(FATAL_ERROR "RETGUARD currently requires Linux x86-64")
endif()

include(CTest)
find_package(Python3 REQUIRED COMPONENTS Interpreter)

option(RETGUARD_BUILD_BENCHMARKS "Build Google Benchmark executables" OFF)
option(RETGUARD_REQUIRE_CET "Require an active CET shadow stack in tests" OFF)

add_library(retguard STATIC src/retguard.c src/retguard_thunks.S)
target_include_directories(retguard PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)
target_compile_features(retguard PUBLIC c_std_11)
target_compile_options(retguard PUBLIC -fno-omit-frame-pointer -fno-optimize-sibling-calls)
target_compile_options(retguard PRIVATE $<$<COMPILE_LANGUAGE:C>:-O2;-fno-stack-protector;-fcf-protection=branch>)
add_library(retguard::retguard ALIAS retguard)
add_library(retguard::manual ALIAS retguard)
add_library(retguard::auto ALIAS retguard)

include(CMakePackageConfigHelpers)
configure_package_config_file(cmake/retguardConfig.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/retguardConfig.cmake
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/retguard)
install(TARGETS retguard EXPORT retguardTargets
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(FILES src/retguard.h DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/retguardConfig.cmake
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/retguard)
install(EXPORT retguardTargets NAMESPACE retguard::
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/retguard)

function(retguard_guard_flags target)
  target_compile_options(${target} PRIVATE -O2 -g -Wall -Wextra -Werror)
endfunction()

function(retguard_target target)
  cmake_parse_arguments(AUTO "" "STACK_FLAG" "SOURCES" ${ARGN})
  if(NOT AUTO_SOURCES OR NOT AUTO_STACK_FLAG OR AUTO_UNPARSED_ARGUMENTS)
    message(FATAL_ERROR "retguard_target requires STACK_FLAG and SOURCES")
  endif()

  set(patched_objects)
  set(index 0)
  foreach(source IN LISTS AUTO_SOURCES)
    math(EXPR index "${index} + 1")
    # A one-source object library lets CMake compile C or C++ normally and
    # gives the patch command an unambiguous object path.
    set(raw_target "${target}_raw_${index}")
    add_library(${raw_target} OBJECT "${source}")
    target_link_libraries(${raw_target} PRIVATE retguard)
    target_compile_definitions(${raw_target} PRIVATE RETGUARD_AUTO)
    set(auto_compiler_flags)
    if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
      list(APPEND auto_compiler_flags -mfentry-name=__retguard_fentry)
    elseif(CMAKE_C_COMPILER_ID STREQUAL "Clang")
      # Clang's generated global constructors miss the return-thunk attribute.
      list(APPEND auto_compiler_flags -mllvm -force-attribute=fn_ret_thunk_extern)
    endif()
    target_compile_options(${raw_target} PRIVATE -O2 -g -Wall -Wextra -Werror -fPIE
      -pg -mfentry ${auto_compiler_flags}
      -mfunction-return=thunk-extern -fasynchronous-unwind-tables
      ${AUTO_STACK_FLAG})

    set(patched "${CMAKE_CURRENT_BINARY_DIR}/${target}_${index}_patched$<CONFIG>.o")
    add_custom_command(OUTPUT "${patched}"
      COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tools/retguard_eh_object.py"
        $<TARGET_OBJECTS:${raw_target}> "${patched}"
      DEPENDS $<TARGET_OBJECTS:${raw_target}>
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/retguard_eh_object.py"
      VERBATIM)
    set_source_files_properties("${patched}" PROPERTIES GENERATED TRUE EXTERNAL_OBJECT TRUE)
    target_sources(${target} PRIVATE "${patched}")
    list(APPEND patched_objects "${patched}")
  endforeach()
  target_link_libraries(${target} PRIVATE retguard)
  set_property(TARGET ${target} PROPERTY RETGUARD_PATCHED_OBJECTS "${patched_objects}")
endfunction()

if(BUILD_TESTING)
  find_package(Threads REQUIRED)
  add_executable(retguard_initialization tests/initialization/fixture.c)
  target_compile_options(retguard_initialization PRIVATE -UNDEBUG)
  target_link_libraries(retguard_initialization PRIVATE retguard)
  target_link_options(retguard_initialization PRIVATE -Wl,--wrap=getrandom)
  retguard_guard_flags(retguard_initialization)
  add_test(NAME manual.initialization COMMAND retguard_initialization)

  add_executable(retguard_manual_api tests/manual_api/fixture.c)
  retguard_guard_flags(retguard_manual_api)
  target_compile_options(retguard_manual_api PRIVATE -UNDEBUG)
  target_link_libraries(retguard_manual_api PRIVATE retguard)
  set(manual_api_flags)
  if(RETGUARD_REQUIRE_CET)
    list(APPEND manual_api_flags --require-cet)
  endif()
  add_test(NAME manual.api COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/manual_api/run.py
    $<TARGET_FILE:retguard_manual_api> ${manual_api_flags})
  add_executable(retguard_manual_smoke tests/manual_smoke/constructor_smoke.cc)
  target_link_libraries(retguard_manual_smoke PRIVATE retguard)
  retguard_guard_flags(retguard_manual_smoke)
  add_test(NAME manual.smoke COMMAND retguard_manual_smoke)

  # The compatibility runners compile a compiler/protection matrix in the
  # build tree and inspect emitted canary and return instructions.
  find_program(RETGUARD_OBJDUMP objdump REQUIRED)
  set(test_flags --cc ${CMAKE_C_COMPILER} --build-dir ${CMAKE_CURRENT_BINARY_DIR}/matrix/manual)
  if(RETGUARD_REQUIRE_CET)
    list(APPEND test_flags --require-cet)
  endif()
  add_test(NAME manual.protections COMMAND ${Python3_EXECUTABLE}
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/manual_protections/run.py ${test_flags})

  if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    foreach(suffix IN ITEMS auto_plain auto_ssp)
      if(suffix STREQUAL "auto_ssp")
        set(stack_flag -fstack-protector-all)
      else()
        set(stack_flag -fno-stack-protector)
      endif()
      add_executable(retguard_${suffix} tests/auto_compatibility/mixed_manual.c)
      retguard_target(retguard_${suffix} STACK_FLAG ${stack_flag}
        SOURCES tests/auto_compatibility/workload.cc tests/auto_compatibility/extra.c)
      get_target_property(auto_objects retguard_${suffix} RETGUARD_PATCHED_OBJECTS)
      set_target_properties(retguard_${suffix} PROPERTIES LINKER_LANGUAGE CXX)
      target_link_libraries(retguard_${suffix} PRIVATE Threads::Threads)
      target_compile_options(retguard_${suffix} PRIVATE -fPIE)
      target_link_options(retguard_${suffix} PRIVATE -pie -Wl,--wrap=__stack_chk_fail)
      retguard_guard_flags(retguard_${suffix})
      if(suffix STREQUAL "auto_ssp")
        target_compile_options(retguard_${suffix} PRIVATE -fstack-protector-all)
      endif()
      add_test(NAME ${suffix}.compatibility COMMAND ${Python3_EXECUTABLE}
        ${CMAKE_CURRENT_SOURCE_DIR}/tests/auto_compatibility/run.py
        $<TARGET_FILE:retguard_${suffix}> $<IF:$<STREQUAL:${suffix},auto_ssp>,--ssp,--plain>
        ${auto_objects})
    endforeach()
  endif()

  if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    set(gadget_flags --compiler $<IF:$<STREQUAL:${CMAKE_C_COMPILER_ID},GNU>,gcc,clang>
      --build-dir ${CMAKE_CURRENT_BINARY_DIR}/matrix/gadget)
    if(RETGUARD_REQUIRE_CET)
      list(APPEND gadget_flags --require-cet)
    endif()
    add_test(NAME manual.checked_return COMMAND ${Python3_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/checked_return/run.py ${gadget_flags})
  endif()
endif()

if(RETGUARD_BUILD_BENCHMARKS)
  find_package(benchmark CONFIG REQUIRED)
  function(retguard_benchmark name)
    add_executable(${name} benchmark/bench_retguard.cc benchmark/bench_targets.c ${ARGN})
    target_link_libraries(${name} PRIVATE retguard benchmark::benchmark)
    target_compile_options(${name} PRIVATE -O3 -DNDEBUG)
  endfunction()
  retguard_benchmark(retguard_bench)
  retguard_benchmark(retguard_bench_cet)
  target_compile_options(retguard_bench_cet PRIVATE -fstack-protector-all -fcf-protection=full)
  target_link_options(retguard_bench_cet PRIVATE -Wl,-z,shstk)
  include(CheckCCompilerFlag)
  check_c_compiler_flag(-ffixed-r11 RETGUARD_HAS_FIXED_R11)
  foreach(suffix IN ITEMS gadget gadget_cet)
    retguard_benchmark(retguard_bench_${suffix})
    target_compile_definitions(retguard_bench_${suffix} PRIVATE RETGUARD_GADGET_BENCH)
    if(CMAKE_C_COMPILER_ID STREQUAL "GNU" OR RETGUARD_HAS_FIXED_R11)
      target_compile_options(retguard_bench_${suffix} PRIVATE -ffixed-r11)
      if(CMAKE_C_COMPILER_ID STREQUAL "Clang")
        target_compile_definitions(retguard_bench_${suffix} PRIVATE RETGUARD_CLANG_FIXED_R11)
      endif()
    endif()
  endforeach()
  target_compile_options(retguard_bench_gadget_cet PRIVATE -fstack-protector-all -fcf-protection=full)
  target_link_options(retguard_bench_gadget_cet PRIVATE -Wl,-z,shstk)
  if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
    add_executable(retguard_bench_auto benchmark/bench_retguard.cc benchmark/bench_targets.c)
    retguard_target(retguard_bench_auto STACK_FLAG -fno-stack-protector
      SOURCES benchmark/bench_auto_target.c)
    target_link_libraries(retguard_bench_auto PRIVATE benchmark::benchmark)
    target_compile_definitions(retguard_bench_auto PRIVATE RETGUARD_AUTO_BENCH)
    target_compile_options(retguard_bench_auto PRIVATE -O3 -DNDEBUG -fPIE)
    target_link_options(retguard_bench_auto PRIVATE -pie)
  endif()
endif()
