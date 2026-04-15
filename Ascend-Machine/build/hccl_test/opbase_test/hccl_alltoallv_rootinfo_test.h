/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.
 * Description: alltoallv rootinfo test
 */

#ifndef __HCCL_ALLTOALLV_ROOTINFO_TEST_H_
#define __HCCL_ALLTOALLV_ROOTINFO_TEST_H_
#include "hccl_test_common.h"
#include "mpi.h"
#include "hccl_check_common.h"
#include "hccl_opbase_rootinfo_base.h"
namespace hccl {
class HcclOpBaseAlltoallvTest:public HcclOpBaseTest
{
public:
    HcclOpBaseAlltoallvTest();
    virtual ~HcclOpBaseAlltoallvTest();
    virtual int hccl_op_base_test(); //主函数

protected:
    size_t init_malloc_Ksize_by_data() override;
    void init_send_recv_size_by_data(size_t &send_bytes, size_t &recv_bytes) override;

private:
    void malloc_send_recv_buf();
    virtual int check_buf_result();//（recv_buf拷贝到recvbufftemp,并且校验正确性）需要调用check_buf_init，校验正确性要调用check_buf_result_float
    void free_send_recv_buf();
    void cal_execution_time(float time);//统计耗时

    unsigned long long *send_counts;
    unsigned long long *send_disp;
    unsigned long long *recv_counts;
    unsigned long long *recv_disp;
};
}
#endif