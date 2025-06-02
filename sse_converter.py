import json

def _parse_json_pointer(pointer_str: str) -> list:
    """
    JSONポインタ文字列（例: "/foo/bar/0"）をパーツのリスト（例: ['foo', 'bar', '0']）に変換する。
    空のポインタ "" は空リスト [] になる。
    """
    if not pointer_str:
        return []
    return pointer_str.strip('/').split('/')

def _ensure_and_get_parent(root_obj, path_parts: list):
    """
    指定されたパス（パーツのリスト形式）に従ってオブジェクトを辿り、
    ターゲットの親コンテナ（辞書またはリスト）を返す。
    途中のパスが存在しない場合は、適切に辞書またはリストを作成する。
    """
    current = root_obj
    # path_partsの最後の要素はターゲットのキー/インデックスなので、その一つ手前まで辿る
    for i, part_str in enumerate(path_parts[:-1]):
        # 次のパスパーツが数値なら、現在のパーツが保持するべきコンテナはリスト
        child_container_should_be_list = path_parts[i+1].isdigit()

        if part_str.isdigit(): # 現在のパスパーツがインデックスの場合
            idx = int(part_str)
            if not isinstance(current, list):
                raise ValueError(f"パス構造の矛盾: '{'/'.join(path_parts[:i+1])}' 地点でリストを期待しましたが、{type(current)} が見つかりました。")
            
            while len(current) <= idx: # リストの長さが足りなければNoneで埋める
                current.append(None)
            
            # 既存の要素が適切な型（リスト/辞書）でなければ、初期化/置換する
            if current[idx] is None or \
               (child_container_should_be_list and not isinstance(current[idx], list)) or \
               (not child_container_should_be_list and not isinstance(current[idx], dict)):
                current[idx] = [] if child_container_should_be_list else {}
            current = current[idx]
        else: # 現在のパスパーツがキーの場合
            if not isinstance(current, dict):
                raise ValueError(f"パス構造の矛盾: '{'/'.join(path_parts[:i+1])}' 地点で辞書を期待しましたが、{type(current)} が見つかりました。")

            if part_str not in current or \
               (child_container_should_be_list and not isinstance(current.get(part_str), list)) or \
               (not child_container_should_be_list and not isinstance(current.get(part_str), dict)):
                current[part_str] = [] if child_container_should_be_list else {}
            current = current[part_str]
    return current

def _apply_single_delta_operation(root_obj, path_str: str, operation: str, value):
    """
    単一のデルタ操作をルートオブジェクトに適用する。
    """
    if path_str is None or operation is None:
        # print(f"警告: パスまたは操作が不明なためデルタ操作をスキップ。Path: {path_str}, Op: {operation}")
        return

    path_parts = _parse_json_pointer(path_str)

    if not path_parts: # ルートオブジェクト自体への操作
        if operation == 'add':
            if isinstance(root_obj, dict) and isinstance(value, dict):
                root_obj.update(value) # 辞書をマージ
            # 他のルート操作はSSEの例では限定的
        elif operation == 'replace':
            if isinstance(root_obj, dict): # ルートが辞書の場合
                root_obj.clear()
                if isinstance(value, dict): root_obj.update(value)
            # 他の型のルートの置換は、このコンテキストでは想定外
        return

    parent_container = _ensure_and_get_parent(root_obj, path_parts)
    target_key_or_index_str = path_parts[-1]

    if operation == 'add':
        if target_key_or_index_str.isdigit():
            idx = int(target_key_or_index_str)
            if not isinstance(parent_container, list):
                 raise ValueError(f"パス構造の矛盾: '{'/'.join(path_parts[:-1])}' 地点で親がリストであるべきです (インデックス '{idx}' 追加のため)。")
            parent_container.insert(idx, value)
        else:
            if not isinstance(parent_container, dict):
                raise ValueError(f"パス構造の矛盾: '{'/'.join(path_parts[:-1])}' 地点で親が辞書であるべきです (キー '{target_key_or_index_str}' 追加のため)。")
            parent_container[target_key_or_index_str] = value
            
    elif operation == 'replace':
        if target_key_or_index_str.isdigit():
            idx = int(target_key_or_index_str)
            if not isinstance(parent_container, list) or idx >= len(parent_container):
                raise ValueError(f"パス '{path_str}' での置換エラー: 親がリストでないか、インデックス {idx} が範囲外です。")
            parent_container[idx] = value
        else:
            if not isinstance(parent_container, dict):
                 raise ValueError(f"パス構造の矛盾: '{'/'.join(path_parts[:-1])}' 地点で親が辞書であるべきです (キー '{target_key_or_index_str}' 置換のため)。")
            # JSON Patchの'replace'は通常既存パスに適用されるが、ここでは'add'のように振る舞わせる（なければ作成）
            parent_container[target_key_or_index_str] = value

    elif operation == 'append': # カスタムappend操作
        actual_target = None
        is_target_list_idx = target_key_or_index_str.isdigit()

        if is_target_list_idx:
            idx = int(target_key_or_index_str)
            if isinstance(parent_container, list) and idx < len(parent_container):
                actual_target = parent_container[idx]
        elif isinstance(parent_container, dict):
            actual_target = parent_container.get(target_key_or_index_str)

        if isinstance(actual_target, str) and isinstance(value, str): # 文字列への追記
            if is_target_list_idx: parent_container[int(target_key_or_index_str)] += value
            else: parent_container[target_key_or_index_str] += value
        elif isinstance(actual_target, list): # リストへの要素追加
            actual_target.append(value)
        elif isinstance(value, dict) and isinstance(parent_container, dict): # 辞書へのマージ的追記
            # ターゲットキーが存在しないか、辞書でなければ初期化
            if not isinstance(parent_container.get(target_key_or_index_str), dict):
                parent_container[target_key_or_index_str] = {}
            parent_container[target_key_or_index_str].update(value)
        # else: print(f"警告: 未対応の'append'ケース。Path: {path_str}, Target type: {type(actual_target)}, Value type: {type(value)}")

def sse_to_json_converter(sse_data_string: str) -> dict:
    """
    デルタ更新を含むSSE（Server-Sent Events）データ文字列を、
    単一の統合されたJSONオブジェクトに変換する。
    """
    consolidated_json = {}  # ここに最終的なJSONが構築される
    
    current_event_name = None
    current_data_lines = [] # イベントのデータ部分を格納（複数行対応）
    full_data_str_for_event = "" # デバッグや[DONE]判定用

    for line in sse_data_string.splitlines():
        line = line.strip()

        if not line: # 空行はイベントの区切り
            if current_event_name and current_data_lines:
                full_data_str_for_event = "".join(current_data_lines)

                if current_event_name == 'delta_encoding':
                    pass # バージョン情報など、データ統合には直接関係なし
                elif current_event_name == 'delta':
                    try:
                        delta_instruction = json.loads(full_data_str_for_event)
                        
                        # パターン1: 'v'キーに操作のリストが含まれる場合
                        if isinstance(delta_instruction.get('v'), list) and \
                           'p' not in delta_instruction and 'o' not in delta_instruction:
                            for single_op in delta_instruction['v']:
                                _apply_single_delta_operation(
                                    consolidated_json,
                                    single_op.get('p'),
                                    single_op.get('o'),
                                    single_op.get('v')
                                )
                        # パターン2: 単一の操作（ルートへの'patch'操作も含む）
                        elif 'o' in delta_instruction:
                            path = delta_instruction.get('p')
                            op_type = delta_instruction.get('o')
                            op_value = delta_instruction.get('v')

                            if op_type == 'patch' and path == "": # ルートへの'patch'操作
                                if isinstance(op_value, list): # 'v'は操作のリスト
                                    for sub_operation in op_value:
                                        _apply_single_delta_operation(
                                            consolidated_json,
                                            sub_operation.get('p'),
                                            sub_operation.get('o'),
                                            sub_operation.get('v')
                                        )
                            else: # 通常の単一操作
                                _apply_single_delta_operation(consolidated_json, path, op_type, op_value)
                    
                    except json.JSONDecodeError as e:
                        # print(f"JSONデコードエラー: '{full_data_str_for_event}'. Error: {e}")
                        pass 
                    except Exception as e:
                        # print(f"デルタ適用エラー '{full_data_str_for_event}': {e}")
                        pass
                
                elif full_data_str_for_event == '[DONE]': # [DONE]マーカー
                    break 

            current_event_name = None
            current_data_lines = []
            if full_data_str_for_event == '[DONE]': break # 外側のループも抜ける

        elif line.startswith('event:'):
            current_event_name = line.split(':', 1)[1].strip()
        elif line.startswith('data:'):
            current_data_lines.append(line.split(':', 1)[1].strip())
        
    return consolidated_json

# --- ここから下は、ろくちゃんが使う時のサンプルやで ---
if __name__ == '__main__':
    # SSEレスポンスをここに貼ってな
    sample_sse_response = """

"""

    print("SSEレスポンスを変換中...")
    final_json_object = sse_to_json_converter(sample_sse_response)
    
    print("\n--- 変換後のJSONオブジェクト ---")
    print(json.dumps(final_json_object, indent=2, ensure_ascii=False))
    