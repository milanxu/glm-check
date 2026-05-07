import sys
import time
import json
import logging
from pathlib import Path
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, QCheckBox,
    QGroupBox, QStatusBar, QMessageBox, QTabWidget, QTextBrowser
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QIcon

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('glm_assistant.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class ConfigManager:
    def __init__(self, config_path='config.json'):
        self.config_path = Path(config_path)
        self.config = self._load_config()

    def _load_config(self):
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save_config(self):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)

    def get(self, key, default=None):
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def set(self, key, value):
        keys = key.split('.')
        config = self.config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value


class TokenValidator:
    def __init__(self):
        self.api_url = "https://bigmodel.cn/api/user/info"
        self.freeze_check_url = "https://bigmodel.cn/api/biz/customer/getLoginFreezePopupFlag"

    def validate(self, username, password):
        import requests
        try:
            session = requests.Session()

            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            logger.info(f"正在调用登录冻结检查 API...")
            freeze_url = f"{self.freeze_check_url}/{username}/password"
            logger.info(f"请求URL: {freeze_url}")

            freeze_response = session.get(freeze_url, headers=headers, timeout=10)
            logger.info(f"冻结检查响应状态码: {freeze_response.status_code}")
            logger.info(f"冻结检查响应内容: {freeze_response.text}")

            if freeze_response.status_code == 200:
                freeze_data = freeze_response.json()
                logger.info(f"冻结检查响应数据: {freeze_data}")

            logger.info(f"正在调用登录 API...")
            login_url = "https://bigmodel.cn/api/auth/login"
            logger.info(f"请求URL: {login_url}")
            logger.info(f"请求头: {headers}")

            import uuid
            anonymous_id = str(uuid.uuid4()).replace('-', '')

            login_payload = {
                "phoneNumber": "",
                "countryCode": "",
                "username": username,
                "smsCode": "",
                "password": password,
                "loginType": "password",
                "grantType": "customer",
                "userType": "PERSONAL",
                "userCode": "",
                "appId": "",
                "anonymousId": anonymous_id
            }
            logger.info(f"登录请求参数: {login_payload}")

            response = session.post(login_url, json=login_payload, headers=headers, timeout=10)

            logger.info(f"登录响应状态码: {response.status_code}")
            logger.info(f"登录响应内容: {response.text}")

            if response.status_code == 200:
                data = response.json()
                logger.info(f"解析后的响应数据: {data}")

                if data.get('code') == 200 or data.get('success'):
                    token = data.get('data', {}).get('access_token')
                    if token:
                        logger.info(f"Token 获取成功: {token[:50]}...")
                        return True, token

                error_msg = data.get('message', '登录失败')
                logger.warning(f"登录失败，错误信息: {error_msg}")
                return False, error_msg
            else:
                error_msg = f"HTTP错误: {response.status_code}"
                logger.error(error_msg)
                return False, error_msg

        except requests.exceptions.Timeout:
            error_msg = "连接超时，请检查网络"
            logger.error(error_msg)
            return False, error_msg
        except requests.exceptions.ConnectionError:
            error_msg = "无法连接到服务器"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"验证失败: {str(e)}"
            logger.error(error_msg)
            return False, error_msg


class GrabWorker(QThread):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str, bool)
    success_signal = pyqtSignal()

    def __init__(self, config_manager, username, password, token=None):
        super().__init__()
        self.config = config_manager
        self.username = username
        self.password = password
        self.token = token
        self.is_running = False
        self.driver = None

    def run(self):
        from selenium import webdriver
        from selenium.webdriver.edge.service import Service
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.microsoft import EdgeChromiumDriverManager

        self.is_running = True
        self.log_signal.emit("正在初始化浏览器...")

        try:
            edge_options = Options()
            if self.config.get('selenium.headless', False):
                edge_options.add_argument('--headless')

            import os
            edge_paths = [
                os.path.expandvars(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                os.path.expandvars(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            ]

            edge_binary = None
            for path in edge_paths:
                if os.path.exists(path):
                    edge_binary = path
                    break

            if edge_binary:
                edge_options.binary_location = edge_binary
                self.log_signal.emit(f"找到 Edge: {edge_binary}")
            else:
                self.log_signal.emit("警告: 未找到 Edge 浏览器，将使用默认路径")

            driver_path = r"C:\WebDriver\msedgedriver.exe"
            if os.path.exists(driver_path):
                service = Service(driver_path)
                self.log_signal.emit(f"使用本地 EdgeDriver: {driver_path}")
            else:
                service = Service(EdgeChromiumDriverManager().install())
                self.log_signal.emit("使用自动下载的 EdgeDriver")

            self.driver = webdriver.Edge(service=service, options=edge_options)
            self.driver.implicitly_wait(self.config.get('selenium.implicit_wait', 10))

            self.log_signal.emit("浏览器初始化完成，正在登录...")
            self._login()

            self.log_signal.emit("正在跳转到 GLM Coding 页面...")
            self.driver.get(self.config.get('bigmodel.coding_url'))

            refresh_interval = self.config.get('refresh_interval', 0.5)
            target_plans = self.config.get('target_plans', ['Pro', 'Max'])

            self.log_signal.emit(f"开始监控抢购，刷新间隔: {refresh_interval}秒")
            self.log_signal.emit(f"目标套餐: {', '.join(target_plans)}")

            while self.is_running:
                try:
                    # 检测访问人数较多提示
                    crowded_msg = self.driver.find_elements(By.ID, 'msg')
                    if crowded_msg:
                        msg_text = crowded_msg[0].text
                        if "访问人数较多" in msg_text:
                            self.log_signal.emit("检测到访问人数较多，点击刷新...")
                            try:
                                refresh_link = self.driver.find_element(By.ID, 'refreshLink')
                                self.driver.execute_script("arguments[0].click();", refresh_link)
                            except:
                                self.driver.refresh()
                            continue

                    # 检测抢购人数过多按钮
                    try:
                        crowded_btn = self.driver.find_element(By.XPATH, '//button[contains(@class, "buy-btn") and contains(@class, "is-disabled")]')
                        btn_text = crowded_btn.text
                        if "抢购人数过多" in btn_text or "刷新再试" in btn_text:
                            self.log_signal.emit("检测到抢购人数过多，正在刷新页面...")
                            self.driver.refresh()
                            continue
                    except:
                        pass

                    for plan_name in target_plans:
                        purchase_button = self._find_purchase_button(plan_name)
                        if purchase_button:
                            self.log_signal.emit(f"检测到 {plan_name} 可购买，正在点击...")
                            purchase_button.click()
                            self._handle_purchase_confirmation()
                            self.success_signal.emit()
                            return

                except Exception as e:
                    logger.debug(f"本次检查未发现购买按钮: {e}")

                time.sleep(refresh_interval)

        except Exception as e:
            self.log_signal.emit(f"错误: {str(e)}")
            self.status_signal.emit(str(e), False)
        finally:
            if self.driver:
                self.driver.quit()
                self.log_signal.emit("浏览器已关闭")

    def _login(self):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        self.driver.get(self.config.get('bigmodel.login_url'))
        self.log_signal.emit(f"当前页面URL: {self.driver.current_url}")

        self.log_signal.emit("等待页面加载...")
        wait = WebDriverWait(self.driver, 10)
        retry_count = 0

        while True:
            self.log_signal.emit(f"[调试] 检查页面状态... (第{retry_count}次)")
            try:
                try:
                    crowded_msg = self.driver.find_element(By.ID, 'msg')
                    self.log_signal.emit(f"[调试] 找到msg元素，文本: {crowded_msg.text}")
                    if crowded_msg and "访问人数较多" in crowded_msg.text:
                        self.log_signal.emit("[调试] 检测到访问人数较多提示")
                        refresh_link = self.driver.find_element(By.ID, 'refreshLink')
                        self.log_signal.emit("[调试] 找到刷新链接，准备点击")
                        self.driver.execute_script("arguments[0].click();", refresh_link)
                        self.log_signal.emit("[调试] 已点击刷新链接")
                        time.sleep(3)
                        retry_count += 1
                        continue
                    else:
                        self.log_signal.emit("[调试] msg元素存在但文本不匹配")
                except Exception as e:
                    self.log_signal.emit(f"[调试] 未找到访问人数提示: {str(e)}")

                self.log_signal.emit("[调试] 查找登录表单元素...")
                password_tab = wait.until(
                    EC.presence_of_element_located((By.XPATH, '//div[@id="tab-password" and @aria-controls="pane-password"]'))
                )
                username_input = wait.until(
                    EC.presence_of_element_located((By.XPATH, '//input[@placeholder="请输入用户名/邮箱/手机号"]'))
                )
                self.log_signal.emit(f"页面加载成功 (重试次数: {retry_count})")
                break
            except Exception as e:
                retry_count += 1
                self.log_signal.emit(f"页面未完全加载，正在刷新... (第{retry_count}次), 错误: {str(e)}")
                self.driver.refresh()
                time.sleep(2)

        try:
            password_tab = wait.until(
                EC.element_to_be_clickable((By.XPATH, '//div[@id="tab-password" and @aria-controls="pane-password"]'))
            )
            password_tab.click()
            self.log_signal.emit("已点击账号登录标签")

            username_input = wait.until(
                EC.presence_of_element_located((By.XPATH, '//input[@placeholder="请输入用户名/邮箱/手机号"]'))
            )
            username_input.clear()
            username_input.send_keys(self.username)
            self.log_signal.emit("用户名已输入")

            password_input = wait.until(
                EC.presence_of_element_located((By.XPATH, '//input[@placeholder="请输入密码"]'))
            )
            password_input.clear()
            password_input.send_keys(self.password)
            self.log_signal.emit("密码已输入")

            time.sleep(1)

            try:
                login_button = wait.until(
                    EC.element_to_be_clickable((By.XPATH, '//button[contains(@class, "login-btn")]//span[contains(text(), "登录")]'))
                )
            except:
                self.log_signal.emit("使用备用方法查找登录按钮...")
                login_button = self.driver.find_element(By.XPATH, '//button[contains(@class, "login-btn")]')

            self.driver.execute_script("arguments[0].click();", login_button)
            self.log_signal.emit("登录按钮已点击，等待跳转...")

            time.sleep(5)
            self.log_signal.emit(f"登录后页面URL: {self.driver.current_url}")

        except Exception as e:
            self.log_signal.emit(f"密码登录失败: {str(e)}")
            logger.error(f"登录失败详细信息: {str(e)}")
            raise

        self.log_signal.emit("登录请求已发送，等待页面跳转...")
        time.sleep(3)

    def _find_purchase_button(self, plan_name):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            xpath = f"//button[contains(text(), '{plan_name}')] | //a[contains(text(), '{plan_name}')]"
            buttons = self.driver.find_elements(By.XPATH, xpath)
            for btn in buttons:
                if btn.is_displayed() and btn.is_enabled():
                    return btn
        except Exception:
            pass
        return None

    def _handle_purchase_confirmation(self):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            wait = WebDriverWait(self.driver, 10)
            confirm_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, '//button[contains(text(), "确认")] | //button[contains(text(), "立即购买")]'))
            )
            confirm_button.click()
            self.log_signal.emit("购买确认已提交")
        except Exception as e:
            self.log_signal.emit(f"未找到确认按钮或无需确认: {e}")

    def stop(self):
        self.is_running = False
        if self.driver:
            self.driver.quit()


class GLMGrabAssistant(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        self.grab_worker = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("GLM 抢购助手 v1.0")
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        tabs = QTabWidget()
        tabs.addTab(self._create_main_tab(), "抢购")
        tabs.addTab(self._create_settings_tab(), "设置")
        tabs.addTab(self._create_log_tab(), "日志")

        main_layout.addWidget(tabs)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def _create_main_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        account_group = QGroupBox("账户信息")
        account_layout = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("用户名:"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("输入用户名/邮箱/手机")
        row1.addWidget(self.username_input)
        account_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("密码:"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("输入密码")
        self.password_toggle = QPushButton("👁")
        self.password_toggle.setFixedWidth(40)
        self.password_toggle.setCheckable(True)
        self.password_toggle.clicked.connect(self.toggle_password_visibility)
        row2.addWidget(self.password_input)
        row2.addWidget(self.password_toggle)
        account_layout.addLayout(row2)

        account_group.setLayout(account_layout)
        layout.addWidget(account_group)

        target_group = QGroupBox("目标设置")
        target_layout = QHBoxLayout()
        target_layout.addWidget(QLabel("目标套餐:"))
        self.plan_combo = QComboBox()
        self.plan_combo.addItems(["Pro (推荐)", "Max", "Lite", "全部"])
        target_layout.addWidget(self.plan_combo)
        target_group.setLayout(target_layout)
        layout.addWidget(target_group)

        control_layout = QHBoxLayout()
        self.start_button = QPushButton("开始抢购")
        self.start_button.clicked.connect(self.start_grab)
        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self.stop_grab)
        self.stop_button.setEnabled(False)
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)
        layout.addLayout(control_layout)

        self.info_label = QLabel("提示: 请确保已登录智谱 AI 账户，或在开始前输入账户信息")
        self.info_label.setStyleSheet("color: gray; padding: 5px;")
        layout.addWidget(self.info_label)

        layout.addStretch()
        return widget

    def _create_settings_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        refresh_layout = QHBoxLayout()
        refresh_layout.addWidget(QLabel("刷新间隔(秒):"))
        self.refresh_input = QLineEdit()
        self.refresh_input.setText(str(self.config.get('refresh_interval', 0.5)))
        refresh_layout.addWidget(self.refresh_input)
        layout.addLayout(refresh_layout)

        headless_layout = QHBoxLayout()
        headless_layout.addWidget(QLabel("无头模式(后台运行):"))
        self.headless_checkbox = QCheckBox()
        self.headless_checkbox.setChecked(self.config.get('selenium.headless', False))
        headless_layout.addWidget(self.headless_checkbox)
        layout.addLayout(headless_layout)

        save_button = QPushButton("保存设置")
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button)

        layout.addStretch()
        return widget

    def _create_log_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        clear_button = QPushButton("清空日志")
        clear_button.clicked.connect(lambda: self.log_text.clear())
        layout.addWidget(clear_button)

        return widget

    def start_grab(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        if not username:
            QMessageBox.warning(self, "提示", "请输入用户名")
            return

        if not password:
            QMessageBox.warning(self, "提示", "请输入密码")
            return

        if len(password) < 6:
            QMessageBox.warning(self, "提示", "密码长度不能少于6位")
            return

        if password.strip() != password:
            QMessageBox.warning(self, "提示", "密码不能包含首尾空格")
            return

        self.log_text.clear()
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] 正在验证账户信息...")

        validator = TokenValidator()
        is_valid, result = validator.validate(username, password)

        if not is_valid:
            self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] 验证失败: {result}")
            QMessageBox.warning(self, "验证失败", result)
            return

        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] 账户验证成功！")
        token = result

        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始抢购任务...")

        target_plan = self.plan_combo.currentText().split(' ')[0]
        if target_plan == "全部":
            self.config.set('target_plans', ['Pro', 'Max', 'Lite'])
        else:
            self.config.set('target_plans', [target_plan])

        self.grab_worker = GrabWorker(self.config, username, password, token)
        self.grab_worker.log_signal.connect(self.update_log)
        self.grab_worker.status_signal.connect(self.update_status)
        self.grab_worker.success_signal.connect(self.grab_success)
        self.grab_worker.start()

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_bar.showMessage("抢购中...")

    def stop_grab(self):
        if self.grab_worker:
            self.grab_worker.stop()
            self.grab_worker.wait()
            self.update_log("抢购任务已停止")

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_bar.showMessage("已停止")

    def toggle_password_visibility(self):
        if self.password_toggle.isChecked():
            self.password_input.setEchoMode(QLineEdit.Normal)
            self.password_toggle.setText("🔒")
        else:
            self.password_input.setEchoMode(QLineEdit.Password)
            self.password_toggle.setText("👁")

    def update_log(self, message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.append(f"[{timestamp}] {message}")
        logger.info(message)

    def update_status(self, message, is_error):
        if is_error:
            self.status_bar.showMessage(f"错误: {message}", 5000)
        else:
            self.status_bar.showMessage(message)

    def grab_success(self):
        QMessageBox.information(self, "成功", "恭喜！抢购成功！")
        self.stop_grab()

    def save_settings(self):
        try:
            refresh_interval = float(self.refresh_input.text())
            self.config.set('refresh_interval', refresh_interval)
        except ValueError:
            QMessageBox.warning(self, "错误", "刷新间隔必须是数字")
            return

        self.config.set('selenium.headless', self.headless_checkbox.isChecked())
        self.config.save_config()
        QMessageBox.information(self, "成功", "设置已保存")

    def closeEvent(self, event):
        if self.grab_worker and self.grab_worker.isRunning():
            self.grab_worker.stop()
            self.grab_worker.wait()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    window = GLMGrabAssistant()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
