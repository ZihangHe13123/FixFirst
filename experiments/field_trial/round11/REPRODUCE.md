# 复现第十一轮的五个公开机制用例

范围仅为 `public-manifest.json` 的5项；独立新任务已取消，不使用其材料。
本说明提供复现命令，本轮归档后未再重复执行。原实际执行为Python3.12.14/macOS，默认模型44，两个第十轮开关均false。
`release-99c8086/FILE-SHA256.json` 校验公开副本；`SUMMARY.json` 分别记录原件与脱敏副本哈希。
原件保存在忽略的工作目录，公开副本中的路径占位不参与运行。

## 仅校验归档（不运行产品）

在仓库根运行：

```sh
python3 - <<'PY'
import hashlib, json
from pathlib import Path
root = Path('experiments/field_trial/round11/release-99c8086')
for name, expected in json.loads((root / 'FILE-SHA256.json').read_text()).items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
print('archive hashes verified')
PY
```

## 需要重跑时

须有两个Git对象及Python3.12.14。用全新的临时目录，安装所记录的宿主依赖，然后为每一版本单独导出src。
依赖锁是版本清单；本归档不含wheel镜像，不承诺无网络安装或跨平台可用性。
下列命令中的 `python3.12` 应指向3.12.14，运行前自行核对版本。

```sh
R11_RUN=$(mktemp -d)
python3.12 -m venv "$R11_RUN/runtime"
"$R11_RUN/runtime/bin/python" -m pip install -r experiments/field_trial/round11/release-99c8086/host-environment.txt
mkdir "$R11_RUN/baseline" "$R11_RUN/candidate"
git archive 40278e5be5bafbe4ac513f110d0d6178ff9f6cf7 src pyproject.toml | tar -x -C "$R11_RUN/baseline"
git archive 99c8086a2fb5445d05e3e7a9fb6e1ace8b2e9681 src pyproject.toml | tar -x -C "$R11_RUN/candidate"
PYTHONPATH="$R11_RUN/baseline/src" "$R11_RUN/runtime/bin/python" experiments/field_trial/round11/prerequisites.py --output "$R11_RUN/baseline-results"
PYTHONPATH="$R11_RUN/candidate/src" "$R11_RUN/runtime/bin/python" experiments/field_trial/round11/prerequisites.py --output "$R11_RUN/candidate-results"
```

驱动每次从冻结public目录复制，先核对全部初始文件摘要；只执行产品首步明确给出的单文件单行替换。
不读取参考修法来补全建议，不改测试。最多10轮/60分钟，通用建议或无法匹配则停，失败保留。
预期候选：位置专用参数第2轮achieved，健康第1轮achieved，其余三个blocked且无修改；基准仅健康achieved。
这验证机制及保守边界，不是独立性能评估。环境版本不同可能产生不同字节码路径，不能把未测平台视为已通过。
