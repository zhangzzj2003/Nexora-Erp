"""初始规格模板；仅由数据库迁移收录，之后完全由管理员维护。"""


def field(name: str, kind: str = 'text', unit: str = '', options: tuple = ()) -> dict:
    # 初始字段均为选填，不替旧档案猜测参数；选项允许非标准型号补充。
    return dict(name=name, kind=kind, unit=unit, options=list(options), allow_custom=bool(options))


def initial_fields(code: str) -> list[dict]:
    package = field('封装尺寸制式', 'enum', options=('英制', '公制', '制造商专用'))
    drawing = [field('图纸编号'), field('图纸版本')]
    dimensions = [field('长度', 'number', 'mm'), field('宽度', 'number', 'mm'), field('高度', 'number', 'mm')]
    wire = [field('导体材质', 'enum', options=('裸铜', '镀锡铜', '铝')),
            field('线规 AWG'), field('导体截面积', 'number', 'mm²'), field('芯数', 'number'),
            field('绝缘材质', 'enum', options=('PVC', '硅胶', 'PE', 'PTFE')),
            field('颜色'), field('外径', 'number', 'mm'), field('额定电压', 'number', 'V'), field('温度等级')]
    harness = wire + [field('线束长度', 'number', 'mm'), field('长度公差'),
                     field('A 端连接器'), field('B 端连接器'), field('针脚定义'), *drawing]
    if code in ('EL-SR', 'EL-TR'):
        return [field('阻值', 'number', 'Ω'), field('容差', 'enum', options=('±0.1%', '±1%', '±5%')),
                field('额定功率', 'number', 'W'), field('电阻类型', 'enum', options=('厚膜', '薄膜', '绕线', '金属膜')), package]
    if code in ('EL-SC', 'EL-TC'):
        return [field('容量', 'number', 'nF'), field('容差'), field('额定电压', 'number', 'V'),
                field('介质 / 温度特性', 'enum', options=('C0G/NP0', 'X7R', 'X5R', 'Y5V', '电解', '钽')), field('有极性', 'boolean'), package]
    if code == 'EL-IC':
        return [field('芯片功能'), field('接口类型'), field('供电电压', 'number', 'V'), field('引脚数', 'number'), field('温度等级'), package]
    if code in ('EL-DI', 'EL-TS'):
        return [field('器件类型'), field('额定电压', 'number', 'V'), field('额定电流', 'number', 'A'), field('导通参数'), package]
    if code == 'EL-IN':
        return [field('电感量', 'number', 'µH'), field('容差'), field('额定电流', 'number', 'A'), field('直流电阻', 'number', 'Ω'), field('磁芯材质')]
    if code == 'EL-CN':
        return [field('连接器系列'), field('针数', 'number'), field('间距', 'number', 'mm'), field('公母'), field('安装方式')]
    if code == 'EL-PC':
        return [field('层数', 'number'), field('板厚', 'number', 'mm'), field('基材'), field('铜厚'), field('表面处理'), *dimensions, *drawing]
    if code == 'EL-CR':
        return [field('频率', 'number', 'MHz'), field('频率精度'), field('负载电容', 'number', 'pF'), field('供电电压', 'number', 'V')]
    if code == 'EL-SW':
        return [field('开关类型'), field('触点配置'), field('额定电压', 'number', 'V'), field('额定电流', 'number', 'A'), field('线圈电压', 'number', 'V')]
    if code == 'PL-RM':
        return [field('树脂类型', 'enum', options=('ABS', 'PC', 'PC+ABS', 'PP', 'PE', 'PA', 'POM', 'PET')),
                field('树脂牌号'), field('颜色'), field('填充 / 增强材料'), field('填充比例', 'number', '%'),
                field('阻燃等级', 'enum', options=('HB', 'V-2', 'V-1', 'V-0', '5VA', '5VB')),
                field('包装净重', 'number', 'kg'), field('原料批次要求')]
    if code.startswith('PL-'):
        return [field('材质', 'enum', options=('ABS', 'PC', 'PC+ABS', 'PP', 'PA', 'POM')),
                field('颜色'), *dimensions, field('壁厚', 'number', 'mm'), field('阻燃等级'), field('模具编号'), *drawing]
    if code == 'HW-FA':
        return [field('紧固件类型', 'enum', options=('螺丝', '螺母', '垫圈', '铆钉')),
                field('螺纹规格'), field('螺距', 'number', 'mm'), field('长度', 'number', 'mm'),
                field('材质'), field('强度等级'), field('表面处理'), field('执行标准')]
    if code.startswith('HW-'):
        return [field('材质'), field('表面处理'), *dimensions, field('加工公差'), field('重量', 'number', 'g'), *drawing]
    if code in ('WR-HS', 'EL-WR'):
        return harness
    if code.startswith('WR-'):
        return wire + [field('屏蔽方式'), field('长度', 'number', 'm'), *drawing]
    if code.startswith('PK-'):
        return [field('包装类型'), field('材质'), *dimensions, field('厚度', 'number', 'mm'), field('印刷要求')]
    return [field('材质'), *dimensions, *drawing]
