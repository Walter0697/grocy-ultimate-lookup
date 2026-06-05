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
            '__barcode' => $barcode
        ];

        if (!empty($result['image_url'])) {
            $product['__image_url'] = $result['image_url'];
        }
        $product['description'] = $this->buildDescription($barcode, $result, $data['research_status'] ?? null);

        return $product;
    }

    private function buildDescription($barcode, $result, $researchStatus)
    {
        $lines = [];
        $language = $result['name_language'] ?? null;
        $rawName = $result['raw_name'] ?? null;

        if (!empty($rawName) && ($rawName !== ($result['name'] ?? null) || (!empty($language) && $language !== 'en'))) {
            $label = empty($language) ? 'Original name' : 'Original name (' . strtoupper($language) . ')';
            $lines[] = $label . ': ' . $rawName;
        }
        if (!empty($result['alternate_names']) && is_array($result['alternate_names'])) {
            foreach ($result['alternate_names'] as $alternateLanguage => $alternateName) {
                $lines[] = 'Alternate name (' . strtoupper($alternateLanguage) . '): ' . $alternateName;
            }
        }
        if (!empty($result['brand'])) {
            $lines[] = 'Brand: ' . $result['brand'];
        }
        if (!empty($result['quantity'])) {
            $lines[] = 'Quantity: ' . $result['quantity'];
        }
        if (!empty($result['source'])) {
            $lines[] = 'Lookup source: ' . $result['source'];
        }
        if (!empty($result['name_origin'])) {
            $lines[] = 'Name origin: ' . $result['name_origin'];
        }
        if (isset($result['confidence'])) {
            $lines[] = 'Lookup confidence: ' . number_format((float)$result['confidence'], 2);
        }
        if (!empty($researchStatus)) {
            $lines[] = 'English-name research: ' . $researchStatus;
        }
        $lines[] = 'Barcode: ' . $barcode;
        if (!empty($result['raw_url'])) {
            $lines[] = 'Source URL: ' . $result['raw_url'];
        }

        return implode("\n", $lines);
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
