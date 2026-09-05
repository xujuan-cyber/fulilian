<?php
$page = $_GET['page'] ?? 'main';
include($page . '.php');
