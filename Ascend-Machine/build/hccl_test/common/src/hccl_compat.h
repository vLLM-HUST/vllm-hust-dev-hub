#ifndef HCCL_COMPAT_H_
#define HCCL_COMPAT_H_

#include <stdint.h>

#include <hccl/hccl_comm.h>
#include <hccl/hccl_res.h>

#ifdef __cplusplus
extern "C" {
#endif

extern HcclResult HcclGetRootInfoV2(HcclRootInfo *rootInfo);
extern HcclResult HcclCommInitRootInfoV2(uint32_t nRanks, const HcclRootInfo *rootInfo, uint32_t rank, HcclComm *comm);
extern HcclResult HcclCommInitRootInfoConfigV2(uint32_t nRanks, const HcclRootInfo *rootInfo, uint32_t rank,
                                               const HcclCommConfig *config, HcclComm *comm);
extern HcclResult HcclCommInitAllV2(uint32_t ndev, int32_t *devices, HcclComm *comms);
extern HcclResult HcclCommDestroyV2(HcclComm comm);
extern HcclResult HcclGetRankSizeV2(HcclComm comm, uint32_t *rankSize);
extern HcclResult HcclGetRankIdV2(HcclComm comm, uint32_t *rank);
extern HcclResult HcclCommSetMemoryRangeV2(HcclComm comm, void *baseVirPtr, size_t size, size_t alignment, uint64_t flags);
extern HcclResult HcclCommUnsetMemoryRangeV2(HcclComm comm, void *baseVirPtr);
extern HcclResult HcclCommActivateCommMemoryV2(HcclComm comm, void *virPtr, size_t size, size_t offset,
                                               aclrtDrvMemHandle handle, uint64_t flags);
extern HcclResult HcclCommDeactivateCommMemoryV2(HcclComm comm, void *virPtr);

extern HcclResult HcclAllReduceV2(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                  HcclReduceOp op, HcclComm comm, aclrtStream stream);
extern HcclResult HcclAllGatherV2(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                  HcclComm comm, aclrtStream stream);
extern HcclResult HcclBroadcastV2(void *buf, uint64_t count, HcclDataType dataType, uint32_t root, HcclComm comm,
                                  aclrtStream stream);
extern HcclResult HcclReduceV2(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                               HcclReduceOp op, uint32_t root, HcclComm comm, aclrtStream stream);
extern HcclResult HcclScatterV2(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                uint32_t root, HcclComm comm, aclrtStream stream);
extern HcclResult HcclReduceScatterV2(const void *sendBuf, void *recvBuf, uint64_t count, HcclDataType dataType,
                                      HcclReduceOp op, HcclComm comm, aclrtStream stream);
extern HcclResult HcclAlltoAllV2(const void *sendBuf, uint64_t sendCount, HcclDataType sendType, void *recvBuf,
                                 uint64_t recvCount, HcclDataType recvType, HcclComm comm, aclrtStream stream);

#define HcclGetRootInfo HcclGetRootInfoV2
#define HcclCommInitRootInfo HcclCommInitRootInfoV2
#define HcclCommInitRootInfoConfig HcclCommInitRootInfoConfigV2
#define HcclCommInitAll HcclCommInitAllV2
#define HcclCommDestroy HcclCommDestroyV2
#define HcclGetRankSize HcclGetRankSizeV2
#define HcclGetRankId HcclGetRankIdV2
#define HcclCommSetMemoryRange HcclCommSetMemoryRangeV2
#define HcclCommUnsetMemoryRange HcclCommUnsetMemoryRangeV2
#define HcclCommActivateCommMemory HcclCommActivateCommMemoryV2
#define HcclCommDeactivateCommMemory HcclCommDeactivateCommMemoryV2
#define HcclAllReduce HcclAllReduceV2
#define HcclAllGather HcclAllGatherV2
#define HcclBroadcast HcclBroadcastV2
#define HcclReduce HcclReduceV2
#define HcclScatter HcclScatterV2
#define HcclReduceScatter HcclReduceScatterV2
#define HcclAlltoAll HcclAlltoAllV2

#ifdef __cplusplus
}
#endif

#endif