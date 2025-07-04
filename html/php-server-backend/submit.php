<?php
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
if ($_SERVER['REQUEST_METHOD'] == 'OPTIONS') {
	exit(0);
}
// function logs($i){ob_start();echo "<pre>";print_r($i);echo "</pre>";$i=ob_get_contents();ob_end_clean();$f=fopen($_SERVER['DOCUMENT_ROOT']."/log_".date("Y-m-d").".txt",'a');fwrite($f,date("H:i:s")." => ".substr($i,5,-6)."\n\n");fclose($f);}
//if(isset($_POST))logs($_POST);

ini_set('display_errors', 1);
ini_set('display_startup_errors', 1);
error_reporting(E_ALL);

require __DIR__ . '/vendor/autoload.php';

use Dotenv\Dotenv;

Dotenv::createImmutable('/volume1/env/php')->load();

// 4) Читаем переменные
$host =   $_ENV['DB_HOST'];
$db   =   $_ENV['DB_NAME'];
$user =   $_ENV['DB_USER'];
$pass =   $_ENV['DB_PASS'];

// 5) Подключаемся
$conn = new mysqli($host, $user, $pass, $db);
if ($conn->connect_error) {
	die("Ошибка подключения к БД: " . $conn->connect_error);
}
$conn->set_charset("utf8mb4");

// Утилита для очистки номера телефона (удаление плюса и пробелов и т.д.)
function normalize_phone($phone)
{
	return ltrim(preg_replace('/\s+/', '', $phone), '+');
}

// === АВТОРИЗАЦИЯ ПО ЛОГИНУ И ПАРОЛЮ ===
/*if(isset($_POST['username'],$_POST['password']))
{
	$c=curl_init();
	if($c)
	{
		$jd=array(
			'username'		=>$_POST['username'],
			'password'		=>$_POST['password'],
		);
		curl_setopt_array($c,array(
			CURLOPT_URL				=>'http://wifi.lounge-place.ru/login',
			CURLOPT_SSL_VERIFYPEER	=>0,
			CURLOPT_SSL_VERIFYHOST	=>0,
			CURLOPT_RETURNTRANSFER	=>1,
			CURLOPT_CONNECTTIMEOUT	=>10,
			CURLOPT_TIMEOUT			=>10,
			CURLOPT_FOLLOWLOCATION	=>1,
			CURLOPT_MAXREDIRS		=>5,
			CURLOPT_POST			=>1,
			CURLOPT_POSTFIELDS		=>$jd,
		));
		if($d=curl_exec($c)){
			//$i=curl_getinfo($c);
			logs($d);
		}
		else{
			logs(curl_error($c));
		}
		curl_close($c);
		?>
$(if error == "")Please log in to use the internet hotspot service $(if trial == 'yes')<br />Free trial available, <a href="$(link-login-only)?dst=$(link-orig-esc)&amp;username=T-$(mac-esc)">click here</a>.$(endif)
$(endif)
$(if error)$(error)$(endif)
		<?
	}
	exit;
}*/

if (isset($_POST['test'])) {
	$m = isset($_POST['tmac']) ? str_replace("'", "''", $_POST['tmac']) : 0;
	$i = isset($_POST['tip']) ? str_replace("'", "''", $_POST['tip']) : 0;
	if ($m && $i) {
		$data = $conn->query("SELECT `id` FROM `wifi_authorizations` WHERE `mac_address`='" . $m . "' AND `ip_address`='" . $i . "' AND `date`>'" . (strtotime('now') - (60 * 30)) . "'");
		$row = mysqli_num_rows($data);
		if ($row) echo 'ok';
	}
	exit;
}

// === СТАРАЯ ЛОГИКА ДЛЯ СОХРАНЕНИЯ MAC/IP/PHONE ===
if (isset($_POST['phone'], $_POST['mac'], $_POST['ip'])) {
	$phone = $_POST['phone'] ?? '';
	$mac = $_POST['mac'] ?? '';
	$ip = $_POST['ip'] ?? '';
	if (!empty($phone) && !empty($mac) && !empty($ip)) {
		$phone = normalize_phone($phone);
		$stmt = $conn->prepare("INSERT INTO `wifi_authorizations` (`mac_address`, `ip_address`, `telegram_id`, `phone_number`,`date`) VALUES (?, ?, 0, ?, '" . strtotime('now') . "')");
		if (!$stmt) {
			die("Ошибка подготовки запроса: " . $conn->error);
		}
		$stmt->bind_param("sss", $mac, $ip, $phone);
		if ($stmt->execute()) {
			echo "OK";
		} else {
			echo "Ошибка записи: " . $stmt->error;
		}
		$stmt->close();
		$conn->close();
		exit;
	}
}

// === НОВЫЙ БЛОК ДЛЯ ОБНОВЛЕНИЯ ДАННЫХ ИЗ БОТА ===
elseif (isset($_POST['telegram_id'], $_POST['phone_number'], $_POST['is_subscribed'], $_POST['user_name'])) {
	$telegram_id = $_POST['telegram_id'] ?? null;
	$phone_number = $_POST['phone_number'] ?? null;
	$is_subscribed = $_POST['is_subscribed'] ?? null;
	$user_name     = $_POST['user_name'] ?? null;

	if (!empty($telegram_id) && !empty($phone_number) && isset($is_subscribed)) {

		$phone_number = normalize_phone($phone_number);
		$is_subscribed = filter_var($is_subscribed, FILTER_VALIDATE_BOOLEAN) ? 1 : 0;

		$stmt = $conn->prepare("SELECT id FROM wifi_authorizations WHERE phone_number = ? ORDER BY created_at DESC LIMIT 1");
		if (!$stmt) {
			http_response_code(500);
			echo "Ошибка подготовки запроса: " . $conn->error;
			exit;
		}

		$stmt->bind_param("s", $phone_number);
		$stmt->execute();
		$result = $stmt->get_result();
		$stmt->close();

		if ($row = $result->fetch_assoc()) {
			$record_id = $row['id'];

			$stmt = $conn->prepare("UPDATE wifi_authorizations SET telegram_id = ?, is_subscribed = ?, user_name = ?  WHERE id = ?");
			if (!$stmt) {
				http_response_code(500);
				echo "Ошибка подготовки запроса (обновление): " . $conn->error;
				exit;
			}

			$stmt->bind_param("iisi", $telegram_id, $is_subscribed, $user_name, $record_id);
			if ($stmt->execute()) {
				echo "OK";

				$data = $conn->query("SELECT `mac_address`,`ip_address`,`phone_number` FROM `wifi_authorizations` WHERE `id`='" . $record_id . "'");
				$row = mysqli_fetch_assoc($data);

				$c = curl_init();
				if ($c) {
					$i = '';
					$jd = json_encode(array(
						'name'			=> $row['mac_address'],
						'password'		=> $telegram_id,
						'attributes'	=> 'tel:' . $phone_number . ',tg-id:' . $telegram_id . ',ip:' . $row['ip_address'],
						//	'group'			=>'radius',
						//	'mac_address'	=>$row['mac_address'],
					));
					curl_setopt_array($c, array(
						//		CURLOPT_URL				=>'https://wifi.lounge-place.ru:65535/rest/ip/hotspot/user',
						CURLOPT_URL				=> 'https://wifi.lounge-place.ru:65535/rest/user-manager/user',
						CURLOPT_HTTPAUTH		=> CURLAUTH_BASIC,
						CURLOPT_USERPWD			=> "iliya:4`P<OjT1",
						CURLOPT_CUSTOMREQUEST	=> 'PUT',
						CURLOPT_SSL_VERIFYPEER	=> 0,
						CURLOPT_SSL_VERIFYHOST	=> 0,
						CURLOPT_RETURNTRANSFER	=> 1,
						CURLOPT_CONNECTTIMEOUT	=> 10,
						CURLOPT_TIMEOUT			=> 10,
						CURLOPT_FOLLOWLOCATION	=> 1,
						CURLOPT_MAXREDIRS		=> 5,
						CURLOPT_POST			=> 1,
						CURLOPT_HTTPHEADER		=> array('Content-Type: application/json'),
						CURLOPT_POSTFIELDS		=> $jd,
					));
					if ($d = curl_exec($c)) {
						//$i=curl_getinfo($c);
						// logs($d);
					} else {
						//logs(curl_error($c));
					}
					curl_close($c);
				}

				$c = curl_init();
				if ($c) {
					$i = '';
					$jd = json_encode(array(
						'user'			=> $row['mac_address'],
						'password'		=> $telegram_id,
						'mac-address'	=> $row['mac_address'],
						'ip'			=> $row['ip_address'],
					));
					// logs($jd);
					//то что активирует сессию.
					curl_setopt_array($c, array(
						CURLOPT_URL				=> 'https://wifi.lounge-place.ru:65535/rest/ip/hotspot/active/login',
						CURLOPT_HTTPAUTH		=> CURLAUTH_BASIC,
						CURLOPT_USERPWD			=> "iliya:4`P<OjT1",
						CURLOPT_SSL_VERIFYPEER	=> 0,
						CURLOPT_SSL_VERIFYHOST	=> 0,
						CURLOPT_RETURNTRANSFER	=> 1,
						CURLOPT_CONNECTTIMEOUT	=> 10,
						CURLOPT_TIMEOUT			=> 10,
						CURLOPT_FOLLOWLOCATION	=> 1,
						CURLOPT_MAXREDIRS		=> 5,
						CURLOPT_POST			=> 1,
						CURLOPT_HTTPHEADER		=> array('Content-Type: application/json'),
						CURLOPT_POSTFIELDS		=> $jd,
					));
					if ($d = curl_exec($c)) {
						curl_close($c);
						//  $i=curl_getinfo($c);
						//	logs($d);

						####
						$c = curl_init();
						if ($c) {
							$display_user = !empty($user_name)
								? "@{$user_name}"
								: "нет username";

							curl_setopt_array($c, array(
								CURLOPT_URL				=> "https://api.telegram.org/bot7520396165:AAGGyn6nUU-KPw-xmSSuF5Oaw4ZjZ0pB24g/sendMessage"
									. "?chat_id=-1002358653308"
									. "&parse_mode=html"
									. "&disable_web_page_preview=True"
									. "&text=" . strtr(urlencode(strtr("<i><b>Новая авторизация Wi-Fi</b></i>
<b>User_name:</b> " . $display_user . " \n
<b>TG-ID:</b> " . $telegram_id . "
<b>TEL:</b> +" . $phone_number . "
<b>IP:</b> " . $row['ip_address'] . "
<b>MAC:</b> <code>" . $row['mac_address'] . "</code>
", array("\r" => ""))), array("\n" => "%0A"))
									. "",
								CURLOPT_SSL_VERIFYPEER	=> 0,
								CURLOPT_SSL_VERIFYHOST	=> 0,
								CURLOPT_RETURNTRANSFER	=> 1,
								CURLOPT_CONNECTTIMEOUT	=> 10,
								CURLOPT_TIMEOUT			=> 10,
								CURLOPT_FOLLOWLOCATION	=> 1,
								CURLOPT_MAXREDIRS		=> 5,
							));
							curl_exec($c);
						}
						####
					} else {
						//	logs(curl_error($c));
					}
				}
			} else {
				http_response_code(500);
				echo "Ошибка при обновлении записи: " . $stmt->error;
			}
			$stmt->close();
		} else {
			http_response_code(404);
			$stmt = $conn->query("UPDATE `wifi_authorizations` SET `telegram_id` = -1 WHERE id = '" . $record_id . "'");
			echo "Номер телефона не найден";
		}

		$conn->close();
		exit;
	}
}

// Если пришёл POST с telegram_id — возвращаем последний mac для него
elseif ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['telegram_id'])) {
	$telegram_id = $_POST['telegram_id'];

	$stmt = $conn->prepare("
        SELECT `mac_address`
        FROM `wifi_authorizations`
        WHERE `telegram_id` = ?
        ORDER BY created_at DESC
        LIMIT 1
    ");

	if (!$stmt) {
		http_response_code(500);
		echo json_encode(['error' => 'Ошибка подготовки запроса: ' . $conn->error]);
		exit;
	}

	$stmt->bind_param("i", $telegram_id);
	$stmt->execute();
	$result = $stmt->get_result();
	$stmt->close();

	if ($row = $result->fetch_assoc()) {
		//echo json_encode(['mac_address' => $row['mac_address']]);
	} else {
		http_response_code(404);
		echo json_encode(['error' => 'MAC-адрес не найден для данного telegram_id']);
	}

	$conn->close();
	exit;
}

http_response_code(400);
echo "Неверные или неполные данные";
