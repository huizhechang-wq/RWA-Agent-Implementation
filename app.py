import sys
import os
import json
import re
from typing import Dict

print("Python 路径:", sys.executable)
print("当前工作目录:", os.getcwd())
print("Python 版本:", sys.version)

try:
    from flask import Flask, render_template, request, jsonify, Response

    print("✅ Flask 导入成功")
except ImportError as e:
    print(f"❌ Flask 导入失败: {e}")
    sys.exit(1)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from agents.trip_agent import TripPlannerAgent
    from config.settings import DEEPSEEK_API_KEY, AMAP_API_KEY

    print("✅ 自定义模块导入成功")
except ImportError as e:
    print(f"❌ 自定义模块导入失败: {e}")
    sys.exit(1)

app = Flask(__name__)

planner = TripPlannerAgent()


def check_api_keys():
    if DEEPSEEK_API_KEY == "您的DeepSeek_API密钥":
        return False, "请先配置DeepSeek API密钥"

    if AMAP_API_KEY == "您的高德地图API密钥":
        return False, "请先配置高德地图API密钥"

    return True, "API密钥配置正常"


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/plan', methods=['POST'])
def plan_trip():
    try:
        data = request.get_json()
        user_input = data.get('input', '').strip()
        voice_style = data.get('voice_style', 'yujie')

        if not user_input:
            return jsonify({'success': False, 'error': '请输入有效的内容'})

        print(f"📝 用户输入: {user_input}")

        # 1. 分析用户需求
        trip_info = planner.extract_trip_info(user_input)
        # 默认模式设为 general_chat 以防止报错
        function_mode = trip_info.get("function_mode", "general_chat")
        is_self_driving = trip_info.get("is_self_driving", False)

        # 获取起点和目的地
        origin = trip_info.get("origin", "当前位置")
        destination = trip_info.get("destination", "旅行目的地")

        print(f"📍 模式识别: {function_mode} | 自驾: {is_self_driving}")

        result = ""

        # --- 分流处理逻辑 ---

        # 情况1: 通用闲聊 (新增处理逻辑)
        if function_mode == "general_chat":
            result = planner.plan_trip(
                function_mode="general_chat",
                user_input=user_input
            )

        # 情况2: 模糊目的地推荐
        elif function_mode == "destination_recommendation":
            result = planner.plan_trip(
                origin=None,
                destination=None,
                transport_mode="自动",
                function_mode="destination_recommendation",
                vague_theme=trip_info.get("vague_theme"),
                user_input=user_input,
                voice_style=voice_style
            )

        # 情况3: 旅游规划
        elif function_mode == "tourism_planning":
            travel_days = trip_info.get("travel_days", 3)
            travel_restrictions = trip_info.get("travel_restrictions", {})
            needs_tourism_guide = "旅游攻略" in user_input or "攻略" in user_input

            if is_self_driving:
                # 自驾游逻辑...
                needs_round_trip = (
                        "来回路线" in user_input or "往返" in user_input or
                        travel_restrictions.get("route_type") == "round_trip"
                )
                if needs_round_trip:
                    result = planner.plan_round_trip_driving_tour(
                        origin=origin, destination=destination,
                        travel_days=travel_days, travel_restrictions=travel_restrictions,
                        include_tourism_guide=needs_tourism_guide, voice_style=voice_style
                    )
                else:
                    result = planner.plan_self_driving_tour(
                        origin=origin, destination=destination,
                        travel_days=travel_days, travel_restrictions=travel_restrictions,
                        include_tourism_guide=needs_tourism_guide, voice_style=voice_style
                    )
            else:
                # 确保 destination 有值
                if not destination or destination in ["旅行", "旅游", "当前位置", "未知目的地"]:
                    destination = user_input

                result = planner.plan_trip(
                    origin=origin,
                    destination=destination,
                    transport_mode="自动",
                    function_mode="tourism_planning",
                    travel_days=travel_days,
                    travel_restrictions=travel_restrictions,
                    voice_style=voice_style,
                    user_input=user_input
                )

        # 情况4: 景点讲解
        elif function_mode == "spot_guide":
            spot_name = trip_info.get("spot_name")
            result = planner.plan_trip(
                origin=None, destination=None, transport_mode="自动",
                function_mode="spot_guide", spot_name=spot_name, voice_style=voice_style
            )

        # 情况5: 纯路径规划 (兜底逻辑)
        else:
            transport_mode = trip_info.get("transport_mode", "自动")
            restrictions = trip_info.get("restrictions", "")

            if is_self_driving:
                # 自驾单纯查路线
                if "来回" in user_input or "往返" in user_input:
                    result = planner.plan_round_trip_driving_tour(
                        origin=origin, destination=destination,
                        travel_days=trip_info.get("travel_days", 4), voice_style=voice_style
                    )
                else:
                    time_available = 0
                    result = planner.plan_self_driving_tour(
                        origin=origin, destination=destination,
                        time_available=time_available, voice_style=voice_style
                    )
            else:
                # 普通路径规划
                origin_geocode, destination_geocode = planner.get_geocoding_for_locations(origin, destination)

                if not origin_geocode or not origin_geocode.get("success"):
                    result = f"❌ 起点 '{origin}' 定位失败"
                elif not destination_geocode or not destination_geocode.get("success"):
                    result = f"❌ 终点 '{destination}' 定位失败"
                else:
                    result = planner.plan_trip(
                        origin=origin,
                        destination=destination,
                        transport_mode=transport_mode,
                        transit_preference=0,
                        function_mode="route_planning",
                        voice_style=voice_style,
                        user_input=user_input
                    )

                    if restrictions:
                        result += f"\n\n🎯 **您的特殊要求**: {restrictions}"

        return jsonify({
            'success': True,
            'result': result,
            'function_mode': function_mode,
            'is_self_driving': is_self_driving
        })

    except Exception as e:
        print(f"❌ 系统错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'系统错误: {str(e)}'})


@app.route('/api/plan/stream', methods=['POST'])
def plan_trip_stream_endpoint():
    """
    【新增】流式行程规划接口 (SSE) - 修复 Generator not JSON serializable 错误
    """
    try:
        data = request.get_json()
        user_input = data.get('input', '').strip()

        if not user_input:
            # 这里的 jsonify 是可以的，因为是直接返回错误对象
            return jsonify({'error': '请输入内容'})

        # 定义生成器函数
        def generate():
            try:
                # 1. 意图识别 (阻塞调用，速度快)
                trip_info = planner.extract_trip_info(user_input)

                # 2. 获取 Agent 的流式生成器
                # 注意：planner.plan_trip_stream 返回的是一个 generator 对象
                generator = planner.plan_trip_stream(**trip_info)

                # 3. 逐个提取内容并推送
                for event_json in generator:
                    # event_json 已经是 json.dumps 过的字符串
                    # SSE 格式要求：以 "data: " 开头，以 "\n\n" 结尾
                    yield f"data: {event_json}\n\n"

                # 结束标志
                yield "data: [DONE]\n\n"

            except Exception as e:
                print(f"流式生成内部错误: {e}")
                import traceback
                traceback.print_exc()
                error_msg = json.dumps({"type": "error", "content": str(e)})
                yield f"data: {error_msg}\n\n"

        # 🚨 关键修复：使用 Flask 的 Response 对象，而不是 jsonify
        # mimetype 必须设置为 text/event-stream
        return Response(generate(), mimetype='text/event-stream')

    except Exception as e:
        print(f"接口错误: {e}")
        return jsonify({'error': str(e)})


def _check_self_driving_request(user_input: str, trip_info: Dict) -> bool:
    """检查是否是自驾游请求"""
    driving_keywords = [
        "自驾", "自己开车", "开车去", "驾车", "开车前往",
        "自驾游", "自己驾车", "开车游玩", "开车旅行",
        "开车去", "开车前往", "自己驾车去", "自己开车去"
    ]

    user_input_lower = user_input.lower()
    for keyword in driving_keywords:
        if keyword in user_input_lower:
            return True

    transport_mode = trip_info.get("transport_mode", "")
    if transport_mode in ["自驾", "驾车", "开车"]:
        return True

    driving_phrases = ["带着车", "自己开", "开我的车", "开自家车", "开车带着"]
    for phrase in driving_phrases:
        if phrase in user_input_lower:
            return True

    long_drive_keywords = ["长途驾驶", "长途开车", "远途自驾", "长途自驾"]
    for keyword in long_drive_keywords:
        if keyword in user_input_lower:
            return True

    return False


def _extract_available_time(user_input: str) -> int:
    """从用户输入中提取可用时间（小时）"""
    patterns = [
        r'(\d+)天时间',
        r'(\d+)天行程',
        r'(\d+)小时',
        r'(\d+)个?钟头',
        r'有(\d+)天',
        r'用(\d+)天',
        r'(\d+)天完成',
        r'(\d+)天到达'
    ]

    for pattern in patterns:
        match = re.search(pattern, user_input)
        if match:
            try:
                days = int(match.group(1))
                return days * 8
            except:
                pass

    chinese_numbers = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '两': 2, '几': 3, '多': 5
    }

    for chinese_num, value in chinese_numbers.items():
        if f"{chinese_num}天" in user_input:
            return value * 8

    return 0


@app.route('/api/voice/speak', methods=['POST'])
def voice_speak():
    """语音播报API"""
    try:
        import base64
        data = request.get_json()
        text = data.get('text', '')
        voice_style = data.get('voice_style', 'yujie')
        content_type = data.get('content_type', 'general')
        optimized = data.get('optimized', True)
        raw_content = data.get('raw_content', '')

        print(f"🎤 语音播报请求: 内容类型={content_type}, 文本长度={len(text)}")

        if not text or len(text.strip()) < 5:
            if raw_content and len(raw_content.strip()) > 10:
                text = raw_content
                print(f"📝 使用原始内容进行智能总结，长度: {len(text)}")
            else:
                return jsonify({
                    'success': False,
                    'error': '文本内容过短，无法合成语音',
                    'suggestion': '请输入至少5个字符的文本'
                })

        if not planner.voice_service:
            return jsonify({
                'success': False,
                'error': '语音服务未初始化',
                'suggestion': '请检查语音服务配置'
            })

        available_voices = planner.voice_service.get_available_voices()
        if voice_style not in available_voices:
            voice_style = 'yujie'
            print(f"⚠️ 请求的音色不可用，使用默认音色: {voice_style}")

        # 使用语音服务合成语音
        audio_data = planner.voice_service.synthesize_speech(
            text,
            voice_style,
            content_type,
            optimized=True
        )

        if audio_data and len(audio_data) > 100:
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            return jsonify({
                'success': True,
                'message': '语音合成成功',
                'audio_data': audio_base64,
                'voice_style': voice_style,
                'optimized': True,
                'audio_length': len(audio_data),
                'format': 'base64'
            })
        else:
            return jsonify({
                'success': False,
                'error': '语音合成失败',
                'suggestion': '请稍后重试'
            })

    except Exception as e:
        print(f"❌ 语音播报接口异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'语音播报失败: {str(e)[:100]}'
        })


@app.route('/api/voice/status', methods=['GET'])
def voice_status():
    """检查语音服务状态"""
    try:
        if not hasattr(planner, 'voice_service') or not planner.voice_service:
            return jsonify({
                'success': False,
                'status': 'disabled',
                'message': '语音服务未启用'
            })
        return jsonify({
            'success': True,
            'status': 'available',
            'message': '语音服务正常'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'error',
            'message': f'语音服务检查出错: {str(e)[:100]}'
        })


@app.route('/api/voice/stop', methods=['POST'])
def voice_stop():
    """停止语音播报"""
    try:
        if hasattr(planner.voice_service, 'engine'):
            planner.voice_service.engine.stop()
        return jsonify({'success': True, 'message': '语音播报已停止'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'停止语音失败: {str(e)}'})


@app.route('/api/voice/styles', methods=['GET'])
def get_voice_styles():
    """获取可用的音色列表"""
    try:
        voices = planner.voice_service.get_available_voices()
        return jsonify({
            'success': True,
            'voices': voices
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'获取音色列表失败: {str(e)}'})


@app.route('/api/voice/set_style', methods=['POST'])
def set_voice_style():
    """设置音色风格"""
    try:
        data = request.get_json()
        voice_style = data.get('voice_style', 'yujie')
        success = planner.voice_service.set_voice_style(voice_style)
        if success:
            return jsonify({
                'success': True,
                'message': f'音色已切换为 {voice_style}',
                'voice_style': voice_style
            })
        else:
            return jsonify({'success': False, 'error': '不支持的音色风格'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'音色切换失败: {str(e)}'})


@app.route('/api/status')
def api_status():
    """API状态检查"""
    api_ok, api_message = check_api_keys()
    return jsonify({
        'api_configured': api_ok,
        'message': api_message
    })


@app.route('/api/test/driving', methods=['POST'])
def test_driving_route():
    """测试自驾游路线规划"""
    try:
        data = request.get_json()
        origin = data.get('origin', '济南')
        destination = data.get('destination', '大同')
        time_available = data.get('time_available', 0)

        origin_geocode, destination_geocode = planner.get_geocoding_for_locations(origin, destination)

        if not origin_geocode or not origin_geocode.get("success"):
            return jsonify({'success': False, 'error': f'起点定位失败: {origin}'})
        if not destination_geocode or not destination_geocode.get("success"):
            return jsonify({'success': False, 'error': f'终点定位失败: {destination}'})

        origin_coord = f"{origin_geocode['lng']},{origin_geocode['lat']}"
        dest_coord = f"{destination_geocode['lng']},{destination_geocode['lat']}"

        route_info = planner.route_planner.plan_driving_route_with_rest_stops(
            origin_coord, dest_coord, time_available=time_available
        )

        if route_info and route_info.get("success"):
            return jsonify({
                'success': True,
                'route_info': route_info,
                'origin': origin,
                'destination': destination
            })
        else:
            return jsonify({
                'success': False,
                'error': route_info.get('error', '自驾路线规划失败') if route_info else '服务暂时不可用'
            })

    except Exception as e:
        return jsonify({'success': False, 'error': f'测试自驾路线失败: {str(e)}'})


@app.route('/api/examples', methods=['GET'])
def get_examples():
    """获取使用示例"""
    examples = {
        "自驾游示例": [
            "从济南自驾到大同，4天时间，想玩2天开车2天，有什么好路线？",
            "开车从长治到西安，5天行程，不想太累，途经哪些城市可以休息游玩？"
        ],
        "智能行程规划": [
            "帮我规划一个5天的自驾游，要驾驶和游玩时间合理分配",
            "从当前位置到三亚，10天时间，不要一直在开车"
        ],
        "途经城市游玩": [
            "从武汉到杭州自驾，途中哪些城市值得停下来玩？",
            "成都到西安的路线，我想在途经的城市也玩一下"
        ]
    }
    return jsonify({
        'success': True,
        'examples': examples,
        'tips': [
            "💡 提示：系统会根据总距离和天数智能分配驾驶和游玩时间",
            "🚗 长途自驾建议：每天驾驶不超过400公里，确保充足休息"
        ]
    })


if __name__ == '__main__':
    # 检查API密钥
    api_ok, api_message = check_api_keys()
    if not api_ok:
        print(f"❌ {api_message}")
        print("请在 config/settings.py 中配置正确的API密钥")
    else:
        print("✅ API密钥配置正常")
        print("🚀 启动智能旅行规划系统...")
        print("🌐 访问地址: http://localhost:5000")

    # 禁用开发服务器警告
    import warnings

    warnings.filterwarnings("ignore", message=".*development server.*")

    app.run(debug=True, host='0.0.0.0', port=5000)