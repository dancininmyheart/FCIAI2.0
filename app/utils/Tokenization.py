import os
import subprocess

import jieba
import nltk
from nltk.tokenize import word_tokenize
# import export_dictionary

nltk.download('punkt')

from subword_nmt import subword_nmt

# 定义 BPE 模型路径和输入输出文件
def subwordt_english():
    bpe_model_path = '../../model/bpe.en'  # 训练好的 BPE 模型
    input_file_path = '../../model/train.en.tok'  # 分词后的训练数据
    output_file_path = '../../model/train.en'  # 输出应用 BPE 后的文件

    # 加载 BPE 模型
    with open(bpe_model_path, 'r', encoding='utf-8') as bpe_file:
        bpe = subword_nmt.BPE(bpe_file)

    # 读取输入文件并应用 BPE 转换
    with open(input_file_path, 'r', encoding='utf-8') as infile, open(output_file_path, 'w', encoding='utf-8') as outfile:
        for line in infile:
            # 对每一行应用 BPE 转换
            bpe_line = bpe.process_line(line.strip())
            outfile.write(bpe_line + '\n')

    print(f"BPE application complete. Output written to {output_file_path}")

def subwordt_chinese():
    bpe_model_path = '../../model/bpe.zh'  # 训练好的 BPE 模型
    input_file_path = '../../model/train.zh.tok'  # 分词后的训练数据
    output_file_path = '../../model/train.zh'  # 输出应用 BPE 后的文件

    # 加载 BPE 模型
    with open(bpe_model_path, 'r', encoding='utf-8') as bpe_file:
        bpe = subword_nmt.BPE(bpe_file)

    # 读取输入文件并应用 BPE 转换
    with open(input_file_path, 'r', encoding='utf-8') as infile, open(output_file_path, 'w',
                                                                      encoding='utf-8') as outfile:
        for line in infile:
            # 对每一行应用 BPE 转换
            bpe_line = bpe.process_line(line.strip())
            outfile.write(bpe_line + '\n')

    print(f"BPE application complete. Output written to {output_file_path}")
def Chinese_tokenizer():
    # 打开文件
    with open('../../temp/temp.zh', 'r', encoding='UTF-8') as fR, open('../../model/train.zh.tok', 'w',
                                                                       encoding='UTF-8') as fW:
        # 遍历每一行
        for sent in fR:
            # 分词
            sent_list = jieba.cut(sent.strip())  # 使用 strip() 去掉每行末尾的换行符
            # 将分词结果写入目标文件，并在每个词之间加上空格
            fW.write(' '.join(sent_list) + '\n')  # 每行后加换行符


def English_tokenizer():
    with open('../../temp/temp.en', 'r', encoding='utf-8') as infile, open('../../model/train.en.tok', 'w',
                                                                           encoding='utf-8') as outfile:
        for line in infile:
            # 使用nltk的word_tokenize进行英文分词
            tokens = word_tokenize(line.strip())  # 分词并去除多余的空白
            outfile.write(' '.join(tokens) + '\n')  # 将分词结果写入文件，并加换行符


def run_tokenizer():
    # The tokenizer is optional and intentionally configured outside the repo.
    tokenizer_script = os.environ.get('MOSES_TOKENIZER_PATH')
    if not tokenizer_script:
        raise RuntimeError('MOSES_TOKENIZER_PATH must point to tokenizer.perl')
    command = ['perl', tokenizer_script, '-l', 'en']

    # 使用 subprocess 调用 Perl 脚本
    with open('../../temp/temp.en', 'r', encoding='utf-8') as infile, open('../../model/train.en', 'w', encoding='utf-8') as outfile:
        subprocess.run(command, stdin=infile, stdout=outfile, check=True)


def Tokenizer():
    # export_dictionary()
    Chinese_tokenizer()
    English_tokenizer()
    subwordt_chinese()
    subwordt_english()

# Tokenizer()
