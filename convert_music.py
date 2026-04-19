import os
from pydub import AudioSegment
from tqdm import tqdm  # 如果没安装可以 pip install tqdm，或者删掉相关代码

def batch_convert_m4a(input_dir, output_format="wav"):
    """
    将指定文件夹下的所有 .m4a 文件转换为指定格式 (wav 或 mp3)
    """
    # 检查输出格式
    if output_format not in ["wav", "mp3"]:
        print("仅支持转为 wav 或 mp3")
        return

    # 获取所有 m4a 文件
    files = [f for f in os.listdir(input_dir) if f.endswith(".m4a")]
    
    if not files:
        print(f"在 {input_dir} 中没找到 .m4a 文件")
        return

    print(f"找到 {len(files)} 个文件，准备开始转换...")

    for filename in files:
        input_path = os.path.join(input_dir, filename)
        # 生成输出文件名：把 .m4a 换成目标后缀
        output_filename = os.path.splitext(filename)[0] + f".{output_format}"
        output_path = os.path.join(input_dir, output_filename)

        try:
            # 加载音频
            audio = AudioSegment.from_file(input_path, format="m4a")
            
            # 导出音频
            # 如果转 wav，建议统一采样率为 16000Hz (AI处理标准) 或 44100Hz (高保真)
            audio.export(output_path, format=output_format)
            print(f"成功: {filename} -> {output_filename}")
        except Exception as e:
            print(f"失败: {filename}, 错误原因: {e}")

if __name__ == "__main__":
    # 【请修改这里】你的 m4a 文件所在的文件夹路径
    # 比如：D:/Study/Programming/etrip/etrip心理/arena/data/raw_audio
    target_dir = input("请输入包含 .m4a 文件的文件夹路径: ")
    target_format = input("你想转换成什么格式？(wav/mp3): ").lower()
    
    batch_convert_m4a(target_dir, target_format)