<?php

use Grocy\Helpers\BaseBarcodeLookupPlugin;

class UltimateBarcodeLookupPlugin extends BaseBarcodeLookupPlugin
{
    public const PLUGIN_NAME = 'Ultimate Barcode Lookup';

    protected function ExecuteLookup($barcode)
    {
        $data = $this->requestLookup($barcode);
        if ($data === null || !($data['found'] ?? false) || empty($data['result']['name'])) {
            return null;
        }

        $locationId = $this->Locations[0]->id;
        if ($this->UserSettings['product_presets_location_id'] != -1) {
            $locationId = $this->UserSettings['product_presets_location_id'];
        }

        $quId = $this->QuantityUnits[0]->id;
        if ($this->UserSettings['product_presets_qu_id'] != -1) {
            $quId = $this->UserSettings['product_presets_qu_id'];
        }

        $result = $data['result'];
        $name = $result['normalized_name'] ?? $result['name'];
        if ($this->shouldAppendSourceMarker() && !empty($result['source'])) {
            $name .= ' [' . $result['source'] . ']';
        }

        $product = [
            'name' => $name,
            'location_id' => $locationId,
            'qu_id_purchase' => $quId,
            'qu_id_stock' => $quId,
            '__qu_factor_purchase_to_stock' => 1,
            '__barcode' => $barcode,
            '__ultimate_lookup_source' => $result['source'] ?? null,
            '__ultimate_lookup_confidence' => $result['confidence'] ?? null,
            '__ultimate_lookup_raw_name' => $result['raw_name'] ?? null,
            '__ultimate_lookup_normalized_name' => $result['normalized_name'] ?? $result['name']
        ];

        if (!empty($result['image_url'])) {
            $product['__image_url'] = $result['image_url'];
        }

        return $product;
    }

    private function shouldAppendSourceMarker()
    {
        $value = getenv('ULTIMATE_LOOKUP_APPEND_SOURCE_MARKER') ?: '';
        return in_array(strtolower($value), ['1', 'true', 'yes'], true);
    }

    private function requestLookup($barcode)
    {
        $lookupServiceUrl = getenv('ULTIMATE_LOOKUP_URL') ?: 'http://host.docker.internal:9290';
        $url = rtrim($lookupServiceUrl, '/') . '/lookup/' . rawurlencode($barcode);
        $handle = curl_init($url);
        curl_setopt_array($handle, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 5,
            CURLOPT_TIMEOUT => 15,
            CURLOPT_HTTPHEADER => ['User-Agent: GrocyUltimateLookupPlugin/0.1']
        ]);

        $body = curl_exec($handle);
        $statusCode = curl_getinfo($handle, CURLINFO_RESPONSE_CODE);
        $error = curl_error($handle);
        curl_close($handle);

        if ($body === false || $statusCode !== 200) {
            throw new \Exception('Ultimate lookup service request failed: ' . ($error ?: 'HTTP ' . $statusCode));
        }

        $data = json_decode($body, true);
        if (!is_array($data)) {
            throw new \Exception('Ultimate lookup service returned invalid JSON');
        }

        return $data;
    }
}
