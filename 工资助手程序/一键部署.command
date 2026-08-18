#!/bin/bash
cd "$(dirname "$0")"
echo "正在部署「工资助手」，请等到 Deploy is ready! ..."
npx -y @netlify/mcp@latest --site-id 95ed2b9e-99ec-45dd-89d2-59abed120e8f --proxy-path "https://netlify-mcp.netlify.app/proxy/eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0..FHq-UIk75L0BD24X.vrfDT1kPU3DNV3b4JLNFYxoFBYx5-DxsR424m2lpEcyHBLoYw83vCj3zlclTKKwcaLoTDYlp1z0uUf0RO1kVAWzfZbVLMO2QMsz8kRUOUlhwDs3xW8ns00RtYyjoQEWWBeqT0hVGpFWjMzdV2WOJC3B12CZbsXRzTqxdjrbiWSPznWtr2eyeOLJ96m-_hrblzBhX-CJT7W7NtQzjPRfvw0jXayl5o-f-A-S1vxq6p3i3LRHwPWMXuhMr12Q3A6g268LctlRRWBiR4GxeWke_RnqZPFQ2QhF1VU7NTGjqeOdMpNYpEWtKuoVsQ9D2zCbvc0vSUk3sETgX481jgFOwpJuQWTFNRuzEzX6blrk8r-qhm1PKBJnHOv91byODwEm6rlpMmtAJ.lbmVRTqTvODGYF8JmhhrJw"
echo ""; echo "完成！https://huoran-salary-helper.netlify.app"; echo "按回车关闭。"; read
