# PPT写入功能使用指南（段落层级支持）

## 📋 概述

第四步PPT写入功能已升级支持段落层级结构，实现真正的逐段翻译，取代了原有不稳定的换行符识别方法。

## 🎯 主要改进

### 1. **段落层级写入**
- **精确定位**：基于段落结构精确写入译文
- **格式保持**：保持每个段落内的字体格式
- **逐段翻译**：真正实现段落级别的翻译控制

### 2. **写入模式增强**
- **paragraph**: 逐段翻译（推荐）- 每个段落下方插入对应译文
- **replace**: 替换模式 - 完全替换为译文
- **append**: 追加模式 - 在文本框末尾追加所有译文
- **bilingual**: 双语模式 - 原文译文并列显示

### 3. **智能匹配算法**
- **精确匹配**：优先进行文本完全匹配
- **相似度兜底**：使用相似度算法处理格式差异
- **质量检查**：自动跳过低质量翻译

## 🏗️ 新的数据处理流程

### 输入数据结构
```json
{
  "pages": [
    {
      "page_index": 0,
      "text_boxes": [
        {
          "box_index": 0,
          "paragraphs": [
            {
              "paragraph_index": 0,
              "paragraph_id": "para_0_0",
              "text_fragments": [
                {
                  "text": "原文片段",
                  "translated_text": "译文片段",
                  "color": 0,
                  "bold": true,
                  "font_size": 14.0
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

### 写入处理流程
1. **文本提取**：从段落结构中提取完整原文
2. **形状匹配**：在PPT中找到匹配的文本框
3. **段落写入**：按段落顺序写入原文和译文
4. **格式应用**：保持原有的字体格式

## 🚀 使用方法

### 1. 环境变量设置
```bash
# 设置LibreOffice路径（可选，有默认值）
export LIBREOFFICE_PYTHON="C:/Program Files/LibreOffice/program/python.exe"
export SOFFICE_PATH="C:/Program Files/LibreOffice/program/soffice.exe"

# 启动LibreOffice服务
soffice --headless --accept="socket,host=localhost,port=2002;urp;"
```

### 2. 直接调用edit_ppt.py
```bash
python edit_ppt.py \
  --input "input.pptx" \
  --output "output.odp" \
  --json "translated_data.json" \
  --mode "paragraph"
```

### 3. 通过主控制器使用
```python
from pyuno_controller import pyuno_controller

result = pyuno_controller(
    presentation_path="your_file.pptx",
    stop_words_list=[],
    custom_translations={},
    select_page=[],
    source_language='en',
    target_language='zh',
    bilingual_translation='paragraph'  # 使用段落模式
)
```

## 🧪 测试方法

### 运行测试套件
```bash
# 基本功能测试
python test_ppt_writing.py

# 使用实际PPT文件测试
python test_ppt_writing.py your_test_file.pptx

# 完整流程测试
python test_paragraph_translation.py your_test_file.pptx
```

### 测试内容
-   文本提取功能验证
-   JSON结构验证
-   子进程调用测试
-   多种写入模式测试
-   错误处理测试

## 📊 写入模式详解

### Paragraph模式（推荐）
```
原文段落1
译文段落1

原文段落2
译文段落2
```
- **适用场景**：学术文档、技术资料
- **特点**：对照清晰，便于理解

### Replace模式
```
译文段落1
译文段落2
```
- **适用场景**：纯外文展示
- **特点**：简洁，节省空间

### Append模式
```
原文段落1
原文段落2

译文段落1
译文段落2
```
- **适用场景**：保持原文完整性
- **特点**：原文译文分离

### Bilingual模式
```
原文段落1
译文段落1
原文段落2
译文段落2
```
- **适用场景**：教学材料
- **特点**：交替显示

## 🔧 故障排除

### 常见问题

#### 1. LibreOffice连接失败
```bash
# 检查服务状态
ps aux | grep soffice

# 重启服务
pkill soffice
soffice --headless --accept="socket,host=localhost,port=2002;urp;"
```

#### 2. 文本匹配失败
- 检查原文和PPT中的文本是否一致
- 查看相似度匹配阈值设置
- 验证段落结构是否正确

#### 3. 格式应用问题
- 确认字体信息在JSON中正确保存
- 检查LibreOffice版本兼容性
- 验证shape属性设置

### 日志分析
主要日志位置：
- `logs/edit_ppt.log` - PPT写入日志
- `test_ppt_temp/` - 测试临时文件
- 控制台输出 - 实时日志

## 📈 性能优化

### 建议
1. **预处理验证**：写入前验证JSON结构
2. **批量处理**：一次性处理多个文本框
3. **错误恢复**：单个文本框失败不影响整体
4. **内存管理**：及时清理临时对象

### 限制
- 单个PPT建议不超过100页
- 单个文本框不超过5000字符
- 复杂格式可能需要手动调整

## 🔄 兼容性

### 向后兼容
- 支持旧版本JSON格式读取
- 提供兼容性函数接口
- 自动检测数据结构类型

### 格式支持
- **输入**：PPTX, PPT, ODP
- **输出**：ODP (可转换为PPTX)
- **字体格式**：颜色、粗体、下划线、字号、上下标

## 📞 技术支持

### 调试步骤
1. 检查LibreOffice服务状态
2. 验证JSON数据结构
3. 运行测试脚本诊断
4. 查看详细日志输出

### 常用命令
```bash
# 检查段落结构
python -c "from write_ppt_page_uno import validate_paragraph_structure; print('OK')"

# 测试文本提取
python test_ppt_writing.py

# 完整流程测试
python pyuno_controller.py
```

---

*支持段落层级的PPT写入功能 - 更精确、更稳定、更智能*
