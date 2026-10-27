<?php
/**
 * Plugin Name:       Disha Receptionist
 * Description:       Disha, DhishaAI's AI receptionist, as a chat bubble on every page and a [disha_chat] shortcode. Messages go through WordPress to the Disha API, so no keys reach the visitor's browser.
 * Version:           1.0.0
 * Requires at least: 5.8
 * Requires PHP:      7.4
 * Author:            DhishaAI Complete Analytics
 * License:           GPL-2.0-or-later
 * Text Domain:       disha-receptionist
 */

if (!defined('ABSPATH')) {
    exit;
}

define('DISHA_VERSION', '1.0.0');
define('DISHA_URL', plugin_dir_url(__FILE__));

/* ------------------------------------------------------------------ settings */

function disha_defaults() {
    return array(
        'api_url'    => '',                       // e.g. https://api.dhishaai.com  or  https://xxxx.ngrok-free.dev
        'site_key'   => '',                       // same as SITE_KEY in the API's .env
        'greeting'   => "Hi! I'm Disha from DhishaAI. Ask me about our courses, batches, fees, a free demo class or our services.",
        'label'      => 'Chat with Disha',
        'bubble'     => '1',                      // show the floating bubble on every page
        'voice_url'  => '',                       // optional: the "Talk to Disha AI" page, e.g. https://api.dhishaai.com/disha/
        'chips'      => "What courses do you offer?\nWhen does the next batch start?\nBook a free demo class\nWhere is your office?",
    );
}

function disha_opt($key) {
    $o = get_option('disha_settings', array());
    $d = disha_defaults();
    return isset($o[$key]) ? $o[$key] : $d[$key];
}

add_action('admin_init', function () {
    register_setting('disha_settings_group', 'disha_settings', array(
        'type'              => 'array',
        'sanitize_callback' => 'disha_sanitize_settings',
        'default'           => disha_defaults(),
    ));
});

function disha_sanitize_settings($in) {
    $out = disha_defaults();
    $in  = is_array($in) ? $in : array();
    $out['api_url']   = isset($in['api_url']) ? untrailingslashit(esc_url_raw(trim($in['api_url']))) : '';
    $out['site_key']  = isset($in['site_key']) ? sanitize_text_field($in['site_key']) : '';
    $out['greeting']  = isset($in['greeting']) ? sanitize_textarea_field($in['greeting']) : $out['greeting'];
    $out['label']     = isset($in['label']) ? sanitize_text_field($in['label']) : $out['label'];
    $out['bubble']    = !empty($in['bubble']) ? '1' : '0';
    $out['voice_url'] = isset($in['voice_url']) ? esc_url_raw(trim($in['voice_url'])) : '';
    $out['chips']     = isset($in['chips']) ? sanitize_textarea_field($in['chips']) : $out['chips'];
    return $out;
}

add_action('admin_menu', function () {
    add_options_page('Disha Receptionist', 'Disha Receptionist', 'manage_options', 'disha-receptionist', 'disha_settings_page');
});

add_filter('plugin_action_links_' . plugin_basename(__FILE__), function ($links) {
    array_unshift($links, '<a href="' . esc_url(admin_url('options-general.php?page=disha-receptionist')) . '">Settings</a>');
    return $links;
});

function disha_settings_page() {
    if (!current_user_can('manage_options')) {
        return;
    }
    $test = null;
    if (isset($_POST['disha_test']) && check_admin_referer('disha_test_connection')) {
        $test = disha_test_connection();
    }
    ?>
    <div class="wrap">
        <h1>Disha Receptionist</h1>
        <?php if ($test) : ?>
            <div class="notice notice-<?php echo $test['ok'] ? 'success' : 'error'; ?>"><p><?php echo esc_html($test['message']); ?></p></div>
        <?php endif; ?>
        <form method="post" action="options.php">
            <?php settings_fields('disha_settings_group'); ?>
            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row"><label for="disha_api_url">Disha API address</label></th>
                    <td><input id="disha_api_url" class="regular-text" type="url" name="disha_settings[api_url]" value="<?php echo esc_attr(disha_opt('api_url')); ?>" placeholder="https://api.dhishaai.com">
                        <p class="description">Where the Disha backend runs (your server, or the https ngrok address while testing). No slash at the end.</p></td>
                </tr>
                <tr>
                    <th scope="row"><label for="disha_site_key">Site key</label></th>
                    <td><input id="disha_site_key" class="regular-text" type="password" autocomplete="off" name="disha_settings[site_key]" value="<?php echo esc_attr(disha_opt('site_key')); ?>">
                        <p class="description">The same value as <code>SITE_KEY</code> in the backend's <code>.env</code>. It stays on this server; visitors never see it.</p></td>
                </tr>
                <tr>
                    <th scope="row">Chat bubble</th>
                    <td><label><input type="checkbox" name="disha_settings[bubble]" value="1" <?php checked(disha_opt('bubble'), '1'); ?>> Show the chat bubble on every page</label>
                        <p class="description">Or put <code>[disha_chat]</code> on a page to show the chat inside that page.</p></td>
                </tr>
                <tr>
                    <th scope="row"><label for="disha_label">Bubble label</label></th>
                    <td><input id="disha_label" class="regular-text" type="text" name="disha_settings[label]" value="<?php echo esc_attr(disha_opt('label')); ?>"></td>
                </tr>
                <tr>
                    <th scope="row"><label for="disha_greeting">First message</label></th>
                    <td><textarea id="disha_greeting" class="large-text" rows="3" name="disha_settings[greeting]"><?php echo esc_textarea(disha_opt('greeting')); ?></textarea></td>
                </tr>
                <tr>
                    <th scope="row"><label for="disha_chips">Suggested questions</label></th>
                    <td><textarea id="disha_chips" class="large-text" rows="4" name="disha_settings[chips]"><?php echo esc_textarea(disha_opt('chips')); ?></textarea>
                        <p class="description">One per line. Shown as buttons under the first message.</p></td>
                </tr>
                <tr>
                    <th scope="row"><label for="disha_voice_url">Voice page (optional)</label></th>
                    <td><input id="disha_voice_url" class="regular-text" type="url" name="disha_settings[voice_url]" value="<?php echo esc_attr(disha_opt('voice_url')); ?>" placeholder="https://api.dhishaai.com/disha/">
                        <p class="description">Adds a "Talk to Disha" button that opens the voice page. Leave empty to hide it.</p></td>
                </tr>
            </table>
            <?php submit_button(); ?>
        </form>
        <hr>
        <form method="post">
            <?php wp_nonce_field('disha_test_connection'); ?>
            <p>Save first, then check that WordPress can reach Disha:</p>
            <p><button class="button" name="disha_test" value="1">Test connection</button></p>
        </form>
    </div>
    <?php
}

function disha_api_headers() {
    return array(
        'Content-Type'               => 'application/json',
        'X-Site-Key'                 => disha_opt('site_key'),
        'X-Forwarded-For'            => disha_visitor_ip(),   // the API rate-limits per visitor IP
        'ngrok-skip-browser-warning' => '1',                  // harmless outside ngrok
    );
}

function disha_test_connection() {
    $api = disha_opt('api_url');
    if (!$api) {
        return array('ok' => false, 'message' => 'Enter the Disha API address and save first.');
    }
    $r = wp_remote_get($api . '/health', array('timeout' => 15, 'headers' => disha_api_headers()));
    if (is_wp_error($r)) {
        return array('ok' => false, 'message' => 'Could not reach ' . $api . ': ' . $r->get_error_message());
    }
    if (wp_remote_retrieve_response_code($r) !== 200) {
        return array('ok' => false, 'message' => 'Disha answered with HTTP ' . wp_remote_retrieve_response_code($r) . '. Check the address.');
    }
    // the site key is checked with a call that needs it (and changes nothing)
    $r = wp_remote_get($api . '/web/messages?visitor_id=wp-connection-test', array('timeout' => 15, 'headers' => disha_api_headers()));
    $code = is_wp_error($r) ? 0 : wp_remote_retrieve_response_code($r);
    if ($code === 401) {
        return array('ok' => false, 'message' => 'Disha is reachable, but the site key is wrong. It must match SITE_KEY in the backend .env.');
    }
    return array('ok' => true, 'message' => 'Connected to Disha at ' . $api . '. The chat is ready.');
}

/* ------------------------------------------------------------------ REST proxy (browser -> WordPress -> Disha API) */

function disha_visitor_ip() {
    $ip = isset($_SERVER['REMOTE_ADDR']) ? sanitize_text_field(wp_unslash($_SERVER['REMOTE_ADDR'])) : '';
    return filter_var($ip, FILTER_VALIDATE_IP) ? $ip : '0.0.0.0';
}

function disha_clean_visitor($v) {
    return substr(preg_replace('/[^A-Za-z0-9_-]/', '', (string) $v), 0, 40);
}

/** A light per-IP limit inside WordPress too, so a flood never even reaches the API. */
function disha_too_many($limit = 30) {
    $key   = 'disha_rl_' . md5(disha_visitor_ip());
    $count = (int) get_transient($key);
    if ($count >= $limit) {
        return true;
    }
    set_transient($key, $count + 1, MINUTE_IN_SECONDS);
    return false;
}

add_action('rest_api_init', function () {
    register_rest_route('disha/v1', '/chat', array(
        'methods'             => 'POST',
        'callback'            => 'disha_rest_chat',
        'permission_callback' => '__return_true',   // public chat; protected by the rate limits and the server-side site key
        'args'                => array(
            'visitor_id' => array('required' => true, 'type' => 'string'),
            'text'       => array('required' => true, 'type' => 'string'),
        ),
    ));
    register_rest_route('disha/v1', '/messages', array(
        'methods'             => 'GET',
        'callback'            => 'disha_rest_messages',
        'permission_callback' => '__return_true',
        'args'                => array(
            'visitor_id' => array('required' => true, 'type' => 'string'),
            'after'      => array('required' => false, 'type' => 'integer', 'default' => 0),
        ),
    ));
});

function disha_rest_chat(WP_REST_Request $req) {
    $api = disha_opt('api_url');
    if (!$api) {
        return new WP_REST_Response(array('error' => 'Disha is not set up yet.'), 503);
    }
    if (disha_too_many()) {
        return new WP_REST_Response(array('error' => 'You are sending messages too fast. Please wait a minute.'), 429);
    }
    $vid  = disha_clean_visitor($req->get_param('visitor_id'));
    $text = trim(wp_strip_all_tags((string) $req->get_param('text')));
    if ($vid === '' || $text === '') {
        return new WP_REST_Response(array('error' => 'Empty message.'), 422);
    }
    $r = wp_remote_post($api . '/web/chat', array(
        'timeout' => 90,   // a model answer with tool calls can take a while
        'headers' => disha_api_headers(),
        'body'    => wp_json_encode(array('visitor_id' => $vid, 'text' => mb_substr($text, 0, 2000))),
    ));
    return disha_relay($r);
}

function disha_rest_messages(WP_REST_Request $req) {
    $api = disha_opt('api_url');
    if (!$api) {
        return new WP_REST_Response(array('messages' => array()), 200);
    }
    if (disha_too_many(60)) {
        return new WP_REST_Response(array('messages' => array()), 200);
    }
    $vid = disha_clean_visitor($req->get_param('visitor_id'));
    $url = add_query_arg(array('visitor_id' => $vid, 'after' => absint($req->get_param('after'))), $api . '/web/messages');
    $r   = wp_remote_get($url, array('timeout' => 15, 'headers' => disha_api_headers()));
    return disha_relay($r);
}

function disha_relay($r) {
    if (is_wp_error($r)) {
        return new WP_REST_Response(array('error' => 'Disha is not reachable right now.'), 502);
    }
    $code = wp_remote_retrieve_response_code($r);
    $body = json_decode(wp_remote_retrieve_body($r), true);
    if ($code >= 300 || !is_array($body)) {
        $msg = ($code === 429) ? 'Too many messages. Please wait a minute.' : 'Disha could not answer just now.';
        return new WP_REST_Response(array('error' => $msg), $code >= 300 ? $code : 502);
    }
    $res = new WP_REST_Response($body, 200);
    $res->header('Cache-Control', 'no-store');
    return $res;
}

/* ------------------------------------------------------------------ front end */

function disha_enqueue() {
    wp_enqueue_style('disha-widget', DISHA_URL . 'assets/widget.css', array(), DISHA_VERSION);
    wp_enqueue_script('disha-widget', DISHA_URL . 'assets/widget.js', array(), DISHA_VERSION, true);
    $chips = array_values(array_filter(array_map('trim', explode("\n", (string) disha_opt('chips')))));
    wp_localize_script('disha-widget', 'DishaConfig', array(
        'chatUrl'     => esc_url_raw(rest_url('disha/v1/chat')),
        'messagesUrl' => esc_url_raw(rest_url('disha/v1/messages')),
        'greeting'    => disha_opt('greeting'),
        'label'       => disha_opt('label'),
        'bubble'      => disha_opt('bubble') === '1',
        'voiceUrl'    => disha_opt('voice_url'),
        'avatar'      => DISHA_URL . 'assets/disha.png',
        'chips'       => array_slice($chips, 0, 6),
    ));
}

add_action('wp_enqueue_scripts', function () {
    if (disha_opt('bubble') === '1' && disha_opt('api_url')) {
        disha_enqueue();
    }
});

add_shortcode('disha_chat', function () {
    if (!disha_opt('api_url')) {
        return current_user_can('manage_options') ? '<p><em>Disha: set the API address under Settings &rarr; Disha Receptionist.</em></p>' : '';
    }
    disha_enqueue();
    return '<div class="disha-inline" data-disha-inline></div>';
});
