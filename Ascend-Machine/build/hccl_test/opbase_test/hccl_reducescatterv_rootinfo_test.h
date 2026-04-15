/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.
 * Description: reducescatterv rootinfo test
 */

#ifndef __HCCL_REDUCESCATTERV_ROOTINFO_TEST_H_
#define __HCCL_REDUCESCATTERV_ROOTINFO_TEST_H_
#include "hccl_test_common.h"
#include "mpi.h"
#include "hccl_check_common.h"
#include "hccl_opbase_rootinfo_base.h"
#include <math.h>
namespace hccl
{
#define REDUCESCATTERV_SUM_MAX_RANKSIZE(HcclDataType) int64_t(sqrt(((int64_t(1) << int(HcclDataTypePrecision::CONCAT(HcclDataType, ))) - 1)))
#define REDUCESCATTERV_SUM_RESULE_OVERFLOW(rank_size,HcclDataType) bool(int64_t(rank_size) > REDUCESCATTERV_SUM_MAX_RANKSIZE(HcclDataType))

class HcclOpBaseReducescatterVTest:public HcclOpBaseTest
{
public:
    HcclOpBaseReducescatterVTest();
    virtual ~HcclOpBaseReducescatterVTest();

    virtual int hccl_op_base_test(); //主函数
    void is_data_overflow() override;

protected:
    size_t init_malloc_Ksize_by_data() override;
    void init_send_recv_size_by_data(size_t &send_bytes, size_t &recv_bytes) override;

private:
    virtual int init_buf_val();  //（初始化host_buf，初始化check_buf，拷贝到send_buf） 其中需要调用hccl_host_buf_init
    virtual int check_buf_result();//（recv_buf拷贝到recvbufftemp,并且校验正确性）需要调用check_buf_init，校验正确性要调用check_buf_result_float
    void cal_execution_time(float time);//统计耗时
    void malloc_send_buf();
    void free_send_buf();
    unsigned long long *send_counts;
    unsigned long long *send_disp;
};
}
#endif