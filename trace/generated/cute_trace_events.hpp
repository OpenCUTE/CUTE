// AUTO-GENERATED FROM trace catalog. DO NOT EDIT.
#pragma once
#include <cstddef>
namespace cutetrace {
struct Event { unsigned id, task, fields; };
inline constexpr unsigned TaskControllerTrace_macroInstInsert = 1;
inline constexpr unsigned TaskControllerTrace_macroInstDecodeStart = 2;
inline constexpr unsigned TaskControllerTrace_macroInstDecodeEnd = 3;
inline constexpr unsigned TaskControllerTrace_microTaskIssue = 4;
inline constexpr unsigned TaskControllerTrace_microTaskCommit = 5;
inline constexpr unsigned AMLLoad_taskStart = 6;
inline constexpr unsigned AMLLoad_taskEnd = 7;
inline constexpr unsigned BMLLoad_taskStart = 8;
inline constexpr unsigned BMLLoad_taskEnd = 9;
inline constexpr unsigned CMLLoad_taskStart = 10;
inline constexpr unsigned CMLLoad_taskEnd = 11;
inline constexpr unsigned CMLStore_taskStart = 12;
inline constexpr unsigned CMLStore_taskEnd = 13;
inline constexpr unsigned MTECompute_taskStart = 14;
inline constexpr unsigned MTECompute_taskEnd = 15;
inline constexpr unsigned CMLStore_storeData = 16;
inline constexpr unsigned VectorStore_storeData = 17;
inline constexpr unsigned SystemMemory_request = 18;
inline constexpr unsigned SystemMemory_response = 19;
inline constexpr unsigned SystemCheckpoint_mark = 20;
inline constexpr unsigned SystemCheckpoint_returned = 21;
inline constexpr unsigned SystemMemory_progress = 22;
inline constexpr Event events[] = {
  {1, 1, 2},
  {2, 1, 2},
  {3, 1, 4},
  {4, 1, 3},
  {5, 1, 3},
  {6, 2, 1},
  {7, 2, 1},
  {8, 3, 1},
  {9, 3, 1},
  {10, 4, 1},
  {11, 4, 1},
  {12, 5, 1},
  {13, 5, 1},
  {14, 6, 1},
  {15, 6, 1},
  {16, 5, 3},
  {17, 7, 3},
  {18, 8, 11},
  {19, 8, 11},
  {20, 9, 3},
  {21, 9, 3},
  {22, 8, 5},
};
} // namespace cutetrace
