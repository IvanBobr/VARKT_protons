import krpc
import time


def launch_to_orbit():
    # Подключение к KSP
    conn = krpc.connect(name='Kerbal X Orbital Launch v2')
    vessel = conn.space_center.active_vessel

    # Настройка потоков телеметрии
    ut = conn.add_stream(getattr, conn.space_center, 'ut')
    altitude = conn.add_stream(getattr, vessel.flight(), 'mean_altitude')
    apoapsis = conn.add_stream(getattr, vessel.orbit, 'apoapsis_altitude')
    periapsis = conn.add_stream(getattr, vessel.orbit, 'periapsis_altitude')
    eccentricity = conn.add_stream(getattr, vessel.orbit, 'eccentricity')
    time_to_apoapsis = conn.add_stream(getattr, vessel.orbit, 'time_to_apoapsis')

    print(f"Запуск корабля: {vessel.name}")

    # 1. ПРЕДСТАРТОВАЯ ПОДГОТОВКА
    vessel.control.sas = False
    vessel.control.rcs = False
    vessel.control.throttle = 1.0
    vessel.control.brakes = False

    # Запуск двигателей
    print("Запуск двигателей!")
    vessel.control.activate_next_stage()

    # Ждем отрыва от стартового стола
    while vessel.situation.name != 'flying':
        time.sleep(0.1)
    print("Отрыв от стартового стола!")

    # 2. ВЕРТИКАЛЬНЫЙ ПОДЪЕМ (первые 1000м)
    print("Вертикальный подъем...")
    vessel.auto_pilot.target_pitch_and_heading(90, 90)
    vessel.auto_pilot.engage()

    target_speed = 100
    while vessel.flight(vessel.orbit.body.reference_frame).speed < target_speed:
        time.sleep(0.1)

    # 3. ГРАВИТАЦИОННЫЙ РАЗВОРОТ
    print("Начало гравитационного разворота")

    turn_start_altitude = 1500
    turn_end_altitude = 35000

    while altitude() < 50000:  # Уменьшил максимальную высоту для разворота
        current_alt = altitude()

        if turn_start_altitude < current_alt < turn_end_altitude:
            frac = ((current_alt - turn_start_altitude) /
                    (turn_end_altitude - turn_start_altitude))
            target_pitch = 90 * (1 - frac)
            target_pitch = max(target_pitch, 5)  # Минимальный угол 5 градусов

            vessel.auto_pilot.target_pitch_and_heading(target_pitch, 90)

        # УЛУЧШЕННОЕ УПРАВЛЕНИЕ СТУПЕНЯМИ
        if vessel.thrust < 10 and vessel.control.current_stage > 1:
            # Проверяем, есть ли топливо в текущей ступени
            current_stage_resources = vessel.resources_in_decouple_stage(vessel.control.current_stage - 1)
            liquid_fuel = current_stage_resources.amount('LiquidFuel')
            solid_fuel = current_stage_resources.amount('SolidFuel')

            if liquid_fuel < 0.1 and solid_fuel < 0.1:
                print(f"Отделение ступени {vessel.control.current_stage}")
                vessel.control.activate_next_stage()
                time.sleep(1)  # Пауза после отделения

        time.sleep(0.1)

    # 4. ВЫКЛЮЧЕНИЕ ДВИГАТЕЛЯ ДЛЯ ВЫХОДА НА СУБОРБИТАЛЬНУЮ ТРАЕКТОРИЮ
    print("Выключение двигателя для выхода на баллистическую траекторию")
    vessel.control.throttle = 0.0

    # Ждем достижения целевого апогея (80-85км)
    target_apoapsis = 80000
    while apoapsis() < target_apoapsis:
        print(f"Текущий апогей: {apoapsis():.0f} м")
        time.sleep(2)

    print(f"Достигнут целевой апогей: {apoapsis():.0f} м")

    # 5. КРУГОВАЯ ОРБИТА - ТОЧНОЕ ВРЕМЯ ВКЛЮЧЕНИЯ
    print("Ожидание оптимального времени для круговогоризации...")

    # Ждем пока не окажемся за 45-60 секунд до апогея
    while time_to_apoapsis() > 60:
        time.sleep(1)

    print(f"Начинаем круговоеризацию за {time_to_apoapsis():.1f} сек до апогея")

    # Ориентация по вектору движения
    vessel.auto_pilot.reference_frame = vessel.orbital_reference_frame
    vessel.auto_pilot.target_direction = (0, 1, 0)
    vessel.auto_pilot.wait()

    # Плавное включение двигателя
    vessel.control.throttle = 0.5  # Начинаем с половинной тяги

    target_periapsis = 75000
    last_periapsis = periapsis()

    # Разгоняемся пока перигей растет
    while periapsis() < target_periapsis:
        current_periapsis = periapsis()

        # Если перигей растет медленно - увеличиваем тягу
        if current_periapsis - last_periapsis < 100:
            vessel.control.throttle = min(1.0, vessel.control.throttle + 0.1)
        # Если растет слишком быстро - уменьшаем
        elif current_periapsis - last_periapsis > 500:
            vessel.control.throttle = max(0.3, vessel.control.throttle - 0.1)

        print(f"Перигей: {current_periapsis:.0f} м, Тяга: {vessel.control.throttle * 100:.0f}%")
        last_periapsis = current_periapsis

        # Прерываем если апогей становится слишком высоким
        if apoapsis() > 120000:
            print("⚠️ Слишком высокий апогей! Прерывание.")
            break

        time.sleep(0.5)

    # Выключение двигателя
    vessel.control.throttle = 0.0
    vessel.auto_pilot.disengage()

    # 6. ФИНАЛЬНАЯ КОРРЕКЦИЯ (если нужно)
    if periapsis() < 70000 or eccentricity() > 0.05:
        print("Выполняем финальную коррекцию орбиты...")
        make_orbit_correction(conn, vessel, target_periapsis)

    # 7. РЕЗУЛЬТАТЫ
    print("\n=== РЕЗУЛЬТАТ ВЫВОДА НА ОРБИТУ ===")
    print(f"Апогей: {apoapsis():.0f} м")
    print(f"Перигей: {periapsis():.0f} м")
    print(f"Эксцентриситет: {eccentricity():.3f}")

    if periapsis() > 70000 and eccentricity() < 0.1:
        print("✅ УСПЕХ: Стабильная круговая орбита достигнута!")
    else:
        print("⚠️ Орбита требует дополнительной коррекции")

    return conn


def make_orbit_correction(conn, vessel, target_altitude):
    """Корректировка орбиты для достижения круговой орбиты"""
    ut = conn.add_stream(getattr, conn.space_center, 'ut')
    apoapsis = conn.add_stream(getattr, vessel.orbit, 'apoapsis_altitude')
    periapsis = conn.add_stream(getattr, vessel.orbit, 'periapsis_altitude')

    # Ориентация для коррекции в перигее
    vessel.auto_pilot.reference_frame = vessel.orbital_reference_frame
    vessel.auto_pilot.target_direction = (0, 1, 0)
    vessel.auto_pilot.engage()
    vessel.auto_pilot.wait()

    # Включение на короткое время для поднятия перигея
    vessel.control.throttle = 0.3
    time.sleep(2)  # Короткое включение
    vessel.control.throttle = 0.0

    vessel.auto_pilot.disengage()


# Запуск программы
if __name__ == "__main__":
    try:
        conn = launch_to_orbit()
        print("\nМиссия завершена!")
    except Exception as e:
        print(f"Ошибка: {e}")
    finally:
        # Не закрываем соединение, чтобы можно было продолжить ручное управление
        print("Соединение с KSP активно для ручного управления")