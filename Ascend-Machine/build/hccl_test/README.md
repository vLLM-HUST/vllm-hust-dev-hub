# 	HCCL Test

HCCL Test提供HCCL通信性能与正确性测试

### 构建

* 构建HCCL Test，需配置MPI_HOME为MPI安装路径，ASCEND_DIR为集合通信库路径。${INSTALL_DIR}表示CANN软件安装后的文件存储路径。

  ```shell
  $ make MPI_HOME=/path/to/mpi ASCEND_DIR=${INSTALL_DIR}
  ```

### 环境准备

* 导入集合通信库及MPI库：

  ```shell
  $ export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:${INSTALL_DIR}/lib64:/path/to/mpi/lib
  ```

* 多机集群训练时，需配置环境变量指定host网卡：（HCCL_SOCKET_IFNAME）

  ```shell
  # 配置HCCL的初始化root通信网卡名，HCCL可通过该网卡名获取Host IP，完成通信域创建。
  # 支持以下格式配置：(4种规格自行选择1种即可)
  # 精确匹配网卡
  #export HCCL_SOCKET_IFNAME==eth0,enp0     : 使用指定的eth0或enp0网卡
  #export HCCL_SOCKET_IFNAME=^=eth0,enp0    : 不使用eth0与enp0网卡
  # 模糊匹配网卡
  # export HCCL_SOCKET_IFNAME=eth,enp       : 使用所有以eth或enp为前缀的网卡
  # export HCCL_SOCKET_IFNAME=^eth,enp      : 不使用任何以eth或enp为前缀的网卡
  
  注：网卡名仅为举例说明，并不只对eth,enp网卡生效
  ```
  
* 多机集群训练时，需统计所有节点使用的host网卡信息：

  ```shell
  $ vim hostfile
  ```
  
  ```shell
  # 全部参与训练的节点ip:每节点的进程数
  10.78.130.22:8
  10.78.130.21:8
  ...
  ```

### 执行

* 单节点运行：

  ```shell
  $ mpirun -n 8 ./bin/all_reduce_test -b 8K -e 64M -f 2 -d fp32 -o sum -p 8
  ```

* 多节点运行：（两节点为例）

  ```shell
  $ mpirun -f hostfile -n 16 ./bin/all_reduce_test -b 8K -e 64M -f 2 -d fp32 -o sum -p 8
  ```

### 参数

所有测试都支持相同的参数集：

* NPU数量
  
  * `[-p,--npus <npus used for one node>] ` 每个计算节点上参与训练的npu个数，默认值：当前节点的npu总数
  
* 数据量
  * `-b,--minbytes <min size in bytes>` 数据量起始值，默认值：64M
  * `-e,--maxbytes <max size in bytes>` 数据量结束值，默认值：64M
  * 数据增量通过增量步长或乘法因子参数设置
    * `-i,--stepbytes <increment size>` 增量步长，默认值：(max-min)/10
    
      注：当输入增量步长（-i）为0时，会持续对数据量起始值（-b）进行测试。
    
    * `-f,--stepfactor <increment factor>` 乘法因子，默认值：不开启
  
* HCCL操作参数
  * `-o,--op <sum/prod/max/min>` 集合通信操作归约类型，默认值：sum
  
  * `-r,--root <root>` root节点，broadcast,reduce和scatter操作生效，默认值：0
  
  * `-d,--datatype <int8/int16/int32/fp16/fp32/int64/uint64/uint8/uint16/uint32/fp64>` 数据类型，默认值：fp32（即float32）

  * `-z,--zero_copy <0/1>` 开启0拷贝，allgather, reduce_scatter, broadcast, allreduce操作符合约束条件生效，默认值：0
  
    注：
    #针对执行命令all_reduce_test、reduce_scatter_test、reduce_test：
    Atlas 训练系列产品，支持数据类型int8、int32、int64、fp16、fp32。
    Atlas 300I Duo 推理卡，支持的数据类型int8、int16、int32、fp16、fp32，其中“prod”、“max”、“min”操作不支持int16
    Atlas A2 训练系列产品，支持数据类型int8、int16、int32、int64、fp16、fp32、bfp16，其中“prod”操作不支持int16、bfp16
    Atlas A3 训练系列产品，支持数据类型int8、int16、int32、int64、fp16、fp32、bfp16，其中“prod”操作不支持int16、bfp16
    
    #针对执行命令reduce_scatterv_test：
    Atlas A2 训练系列产品，仅支持单机场景, 针对Atlas 200T A2 Box16 异构子框，仅支持使用单模组的场景，即只使用前8卡或者后8卡
                          支持数据类型int8、int16、int32、fp16、fp32、bfp16, 支持的操作类型为sum、max、min
    Atlas 300I Duo 推理卡，最多支持单机两卡的场景, 支持数据类型：int16、float16、float32, 仅支持操作类型sum

    #针对执行命令all_gatherv_test
    Atlas A2 训练系列产品，仅支持单机场景，针对Atlas 200T A2 Box16 异构子框，仅支持使用单模组的场景，即只使用前8卡或者后8卡
    Atlas 300I Duo 推理卡，最多支持单机两卡的场景。

    #针对执行命令broadcast_test、all_gather_test、alltoallv_test、alltoall_test、scatter_test，支持的数据类型包括：
    int8、int16、int32、fp16、fp32、int64、uint64、uint8、uint16、uint32、fp64、bfp16。
    其中bfp16数据类型仅Atlas A2 训练系列产品、Atlas A3 训练系列产品支持。

    #针对0拷贝功能，有如下使用约束：  
    1.仅支持Atlas A3 训练系列产品。  
    2.仅支持单节点执行命令reduce_scatter_test, all_gather_test, broadcast_test, all_reduce_test
    3.仅支持通信算法的编排展开位置在AI CPU，且通信算子未开启重执行的场景。  
    4.算子send_bytes(与数据量、数据类型、npu总数有关)满足32MB及以上。  
  
* 性能
  * `-n,--iters <iteration count>` 迭代次数，默认值：20
  * `-w,--warmup_iters <warmup iteration count>` 预热迭代次数（不参与性能统计，仅影响HCCL Test执行耗时），默认值：10
  
* 结果校验
  
  * `-c,--check <0/1>` 校验集合通信操作结果正确性（大规模集群场景下，开启结果校验会使HCCL Test执行耗时增加），默认值：1（开启）

### 执行示例

* allreduce

  ```shell
  # 单节点8个NPU
  $ mpirun -n 8 ./bin/all_reduce_test -b 8K -e 64M -f 2 -p 8
  ```

  ```shell
  # 双节点16个NPU
  $ mpirun -f hostfile -n 16 ./bin/all_reduce_test -b 8K -e 64M -f 2 -p 8
  ```

* broadcast

  ```shell
  # 单节点8个NPU
  $ mpirun -n 8 ./bin/broadcast_test -b 8K -e 64M -f 2 -p 8 -r 1
  ```

  ```shell
  # 双节点16个NPU
  $ mpirun -f hostfile -n 16 ./bin/broadcast_test -b 8K -e 64M -f 2 -p 8 -r 1
  ```

* allgather

  ```shell
  # 单节点8个NPU
  $ mpirun -n 8 ./bin/all_gather_test -b 8K -e 64M -f 2 -p 8
  ```

  ```shell
  # 双节点16个NPU
  $ mpirun -f hostfile -n 16 ./bin/all_gather_test -b 8K -e 64M -f 2 -p 8
  ```

* alltoallv

  ```shell
  # 单节点8个NPU
  $ mpirun -n 8 ./bin/alltoallv_test -b 8K -e 64M -f 2 -p 8
  ```

  ```shell
  # 双节点16个NPU
  $ mpirun -f hostfile -n 16 ./bin/alltoallv_test -b 8K -e 64M -f 2 -p 8
  ```

* alltoall

  ```shell
  # 单节点8个NPU
  $ mpirun -n 8 ./bin/alltoall_test -b 8K -e 64M -f 2 -p 8
  ```

  ```shell
  # 双节点16个NPU
  $ mpirun -f hostfile -n 16 ./bin/alltoall_test -b 8K -e 64M -f 2 -p 8
  ```

* reducescatter

  ```shell
  # 单节点8个NPU
  $ mpirun -n 8 ./bin/reduce_scatter_test -b 8K -e 64M -f 2 -p 8
  ```

  ```shell
  # 双节点16个NPU
  $ mpirun -f hostfile -n 16 ./bin/reduce_scatter_test -b 8K -e 64M -f 2 -p 8
  ```

* reduce

  ```shell
  # 单节点8个NPU
  $ mpirun -n 8 ./bin/reduce_test -b 8K -e 64M -f 2 -p 8 -r 1
  ```
  
  ``` shell
  # 双节点16个NPU
  $ mpirun -f hostfile -n 16 ./bin/reduce_test -b 8K -e 64M -f 2 -p 8 -r 1
  ```

### 指定deviceId执行用例

需要在当前计算节点的hccl_test目录下，创建一个可执行文件，例：run.sh。

* 单server场景（启动4，5，6，7卡）

  * 创建可执行文件：

    run.sh文件内容如下：
	```shell
    #HCCL_TEST_USE_DEVS后的数字为需要启动的deviceId
    export HCCL_TEST_USE_DEVS="4,5,6,7"
    $1
	```

  * 用例执行：
	```shell
    mpirun -n 4 ./run.sh "./all_reduce_test -b 8K -e 64M -f 2 -p 4"
	```
  
* 多server场景（计算节点1启动0，1，2，3卡，计算节点2启动4，5，6，7卡）

  * 计算节点1：

    * 创建可执行文件：
    
      run.sh文件内容如下：
	  ```shell
      export HCCL_TEST_USE_DEVS="0,1,2,3"
      $1
	  ```
    
  * 计算节点2：

    * 创建可执行文件：
    
      run.sh文件内容如下：
	  ```shell
      export HCCL_TEST_USE_DEVS="4,5,6,7"
      $1
	  ```
    
  * 用例执行：
	```shell
    mpirun -n 8 -f hostfile ./run.sh "./all_reduce_test -b 8K -e 64M -f 2 -p 4"
	```

