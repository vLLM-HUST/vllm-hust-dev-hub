/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024-2024. All rights reserved.
 * Description: hccl_alltoallvc hccl test
 */

#ifndef __HCCL_ALLTOALLVC_ROOTINFO_TEST_H_
#define __HCCL_ALLTOALLVC_ROOTINFO_TEST_H_

#include "hccl_test_common.h"
#include "mpi.h"
#include "hccl_check_common.h"
#include "hccl_opbase_rootinfo_base.h"

namespace hccl {

class HcclOpBaseAlltoallvcTest : public HcclOpBaseTest
{
public:
    HcclOpBaseAlltoallvcTest();
    virtual ~HcclOpBaseAlltoallvcTest();

    virtual int hccl_op_base_test() override;
protected:
    size_t init_malloc_Ksize_by_data() override;
    void init_send_recv_size_by_data(size_t &send_bytes, size_t &recv_bytes) override;

private:
    void malloc_send_recv_buf();
    int check_buf_result();
    void free_send_recv_buf();
    void cal_execution_time(float time);

    unsigned long long* send_count_matrix; // [rank_size * rank_size]
    unsigned long long* recv_counts;       // 临时保存本rank接收长度用于校验
};

} // namespace hccl

#endif