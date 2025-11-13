from odoo import models, fields, api
from odoo.exceptions import ValidationError
import requests
import base64
from datetime import datetime, timedelta
import logging
import json

from datetime import datetime


_logger = logging.getLogger(__name__)

class OrangeMoneyConfig(models.Model):
    _name = 'orange.money.config'
    _description = 'Configuration Orange Money'
    _rec_name = 'name'

    name = fields.Char(
        string='Nom de la configuration',
        required=True,
        help="Nom descriptif pour cette configuration Orange Money"
    )
    
    # Identifiants API Orange Money (OAuth2)
    client_id = fields.Char(
        string='Client ID',
        required=True,
        help="Client ID fourni par Orange Money pour OAuth2"
    )
    
    client_secret = fields.Char(
        string='Client Secret',
        required=True,
        help="Client Secret fourni par Orange Money pour OAuth2"
    )
    # Configuration des URLs selon la documentation
    base_url = fields.Char(
        string='URL de base API',
        required=True,
        default='https://api.orange-sonatel.com',
        help="URL de base de l'API Orange Money (sandbox ou production)"
    )
    callback_notification_url = fields.Char(
        string='URL de notification',
        required=True,
        default='https://intranet.toubasandaga.sn/orange/webhook',
        help="URL pour les notifications webhook"
    )
    
    # Code marchand (requis pour les QR codes)
    merchant_code = fields.Char(
        string='Code Marchand',
        required=True,
        help="Code marchand à 6 chiffres fourni par Orange Money"
    )
    
    merchant_name = fields.Char(
        string='Nom du Marchand',
        required=True,
        help="Nom du marchand affiché lors des paiements"
    )
    
    # Configuration
    is_active = fields.Boolean(
        string='Configuration Active',
        default=True,
        help="Seule une configuration peut être active à la fois"
    )
    
    environment = fields.Selection([
        ('sandbox', 'Sandbox (Test)'),
        ('production', 'Production')
    ], string='Environnement', default='sandbox', required=True)
    
    default_currency = fields.Selection([
        ('XOF', 'Franc CFA (XOF)'),
    ], string='Devise par défaut', default='XOF', required=True)
    
    # Token d'accès OAuth2
    access_token = fields.Char(
        string='Token d\'accès',
        readonly=True,
        help="Token d'accès OAuth2 généré automatiquement"
    )
    
    token_expires_at = fields.Datetime(
        string='Expiration du token',
        readonly=True,
        help="Date d'expiration du token d'accès"
    )
    
    # Clé publique pour chiffrement PIN
    public_key = fields.Text(
        string='Clé publique',
        readonly=True,
        help="Clé publique RSA pour chiffrer les codes PIN"
    )
    
    public_key_id = fields.Char(
        string='ID de la clé publique',
        readonly=True,
        help="Identifiant de la clé publique"
    )
    
    # Champs de suivi
    created_at = fields.Datetime(
        string='Date de création',
        default=fields.Datetime.now,
        readonly=True
    )
    
    updated_at = fields.Datetime(
        string='Dernière modification',
        default=fields.Datetime.now,
        readonly=True
    )
    
    # Statistiques
    total_transactions = fields.Integer(
        string='Total des transactions',
        compute='_compute_transaction_stats',
        store=False
    )
    
    successful_transactions = fields.Integer(
        string='Transactions réussies',
        compute='_compute_transaction_stats',
        store=False
    )
    
    failed_transactions = fields.Integer(
        string='Transactions échouées',
        compute='_compute_transaction_stats',
        store=False
    )

    api_key = fields.Char(
        string='API Key',
        required=True,
        help="Clé API fournie par Orange pour l\'accès aux services (ex: CCTS@2025)"
    )

    last_webhook_status = fields.Char(
        string="Dernière réponse webhook",
        readonly=True,
        help="Dernière réponse reçue lors de la configuration du webhook."
    )


    @api.depends('is_active')
    def _compute_transaction_stats(self):
        """Calculer les statistiques des transactions"""
        for record in self:
            transactions = self.env['orange.money.transaction'].search([])
            record.total_transactions = len(transactions)
            record.successful_transactions = len(transactions.filtered(lambda t: t.status == 'SUCCESS'))
            record.failed_transactions = len(transactions.filtered(lambda t: t.status in ['FAILED', 'CANCELLED', 'REJECTED']))

    @api.constrains('is_active')
    def _check_single_active_config(self):
        """S'assurer qu'une seule configuration est active"""
        if self.is_active:
            other_active = self.search([('is_active', '=', True), ('id', '!=', self.id)])
            if other_active:
                raise ValidationError("Une seule configuration Orange Money peut être active à la fois.")

    def write(self, vals):
        """Mettre à jour la date de modification"""
        vals['updated_at'] = fields.Datetime.now()
        return super().write(vals)



    def _get_access_token(self):
        """Obtenir un token d'accès OAuth2 selon la documentation Orange Money"""
        try:
            # Vérifier si le token est encore valide
            if self.access_token and self.token_expires_at:
                if fields.Datetime.now() < self.token_expires_at:
                    return self.access_token
            
            # Préparer les données pour OAuth2
            token_url = f"{self.base_url}/oauth/v1/token"
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'client_credentials'
            }
            
            response = requests.post(token_url, headers=headers, data=data, timeout=30)
            
            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get('access_token')
                expires_in = token_data.get('expires_in', 300)  # 5 minutes par défaut selon la doc
                
                # Calculer la date d'expiration avec une marge de sécurité
                expires_at = fields.Datetime.now() + timedelta(seconds=expires_in - 30)
                
                # Sauvegarder le token
                self.write({
                    'access_token': access_token,
                    'token_expires_at': expires_at
                })
                
                return access_token
            else:
                raise Exception(f"Erreur d'authentification OAuth2: {response.status_code} - {response.text}")
                
        except Exception as e:
            raise Exception(f"Erreur lors de l'obtention du token OAuth2: {str(e)}")

    def test_connection(self):
        """Tester la connexion à l'API Orange Money"""
        try:
            # Test 1: Obtenir un token OAuth2
            token = self._get_access_token()
            
            if not token:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Erreur de connexion',
                        'message': 'Impossible d\'obtenir le token OAuth2.',
                        'type': 'danger',
                    }
                }
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connexion réussie',
                    'message': 'La connexion à l\'API Orange Money a été établie avec succès.',
                    'type': 'success',
                }
            }
            
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Erreur de connexion',
                    'message': f'Erreur: {str(e)}',
                    'type': 'danger',
                }
            }


    def generate_qr_code(self, amount, validity=3600, metadata=None , success_url=None, cancel_url=None):
        """Générer un QR code pour paiement marchand"""
        try:
            token = self._get_access_token()
            public_key = self.get_public_key()
            
            # api/payment/callback/<string:transactionId>
            callback_url =  self.callback_notification_url or f"https://intanet.toubasandaga.sn/orange/webhook"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'X-Callback-Url': callback_url, 
                'X-Api-Key': public_key
            }

            _logger.info(f"header : {headers}"  )

            payload = {
                'amount': {
                    'unit': self.default_currency,
                    'value': int(amount)
                },
                'code': self.merchant_code,
                'name': self.merchant_name,
                'validity': validity,  # en secondes, max 86400
                'callbackSuccessUrl': success_url,
                'callbackCancelUrl': cancel_url,
                'metadata': metadata or {}
            }
            _logger.info(f"Payload : {payload} "  )

            response = requests.post(
                f"{self.base_url}/api/eWallet/v4/qrcode",
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                return response.json()
            else:
                raise Exception(f"Erreur API Orange Money: {response.status_code} - {response.text}")
                
        except Exception as e:
            raise Exception(f"Erreur lors de la génération du QR code: {str(e)}")


    def get_public_key(self):
        """Obtenir la clé publique de l'API Orange Money"""
        try:
            token = self._get_access_token()

            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(
                f"{self.base_url}/api/account/v1/publicKeys",
                headers=headers,
                timeout=30
            )

            if response.status_code in [200, 201]:
                public_key_data = response.json()
                public_key = public_key_data.get('key')
                public_key_id = public_key_data.get('keyId')

                # Enregistrer la clé publique et son ID
                self.write({
                    'public_key': public_key,
                    'public_key_id': public_key_id
                })

                return public_key
            else:
                raise Exception(f"Erreur API Orange Money: {response.status_code} - {response.text}")

        except Exception as e:
            raise Exception(f"Erreur lors de l'obtention de la clé publique: {str(e)}")
        

    def get_transaction_status(self, transactionId):
        """
        Vérifier le statut d'une transaction via l'API Orange Money
        et mettre à jour la transaction correspondante dans Odoo.
        """
        try:
            _logger.info(f"Vérification du statut pour transaction_id : {transactionId}")

            token = self._get_access_token()
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }

            url = f"{self.base_url}/api/eWallet/v1/transactions?transactionId={transactionId}"
            _logger.info(f"Requête GET vers {url} avec headers {headers}")

            response = requests.get(url, headers=headers, timeout=30)

            _logger.info(f"Réponse API - Status Code : {response.status_code}")
            _logger.debug(f"Contenu brut : {response.text}")

            if response.status_code != 200:
                _logger.error(f"Erreur API Orange Money : {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'message': f"Erreur API : {response.status_code} - {response.text}"
                }

            data = response.json()
            status = data.get('status', '').upper()
            _logger.info(f"Statut retourné : {status}")

            # Rechercher la transaction dans Odoo
            transaction = self.env['orange.money.transaction'].sudo().search([
                ('transactionId', '=', transactionId)
            ], limit=1)

            if not transaction:
                _logger.warning(f"Aucune transaction trouvée pour transactionId : {transactionId}")
                return {
                    'success': False,
                    'message': f"Aucune transaction trouvée dans Odoo pour transactionId : {transactionId}",
                    'orange_response': data
                }

            # Mettre à jour la transaction si le statut a changé
            if transaction.status != status:
                _logger.info(f"Mise à jour de la transaction {transactionId} : {transaction.status} -> {status}")
                transaction.write({
                    'status': status,
                    'updated_at': fields.Datetime.now(),
                    'orange_response': json.dumps(data)
                })
            else:
                _logger.info(f"Aucun changement de statut pour {transactionId} (statut actuel : {transaction.status})")

            return {
                'success': True,
                'message': 'Statut récupéré avec succès',
                'transaction_status': status,
                'orange_response': data
            }

        except requests.exceptions.Timeout:
            _logger.error("Timeout lors de l'appel à l'API Orange Money")
            return {'success': False, 'message': 'Timeout lors de l\'appel à l\'API Orange Money'}

        except Exception as e:
            _logger.error(f"Erreur inattendue : {str(e)}")
            return {'success': False, 'message': f'Erreur inattendue : {str(e)}'}


    # Actions pour les vues
    def action_view_transactions(self):
        """Action pour voir toutes les transactions"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Transactions Orange Money',
            'res_model': 'orange.money.transaction',
            'view_mode': 'tree,form',
            'domain': [],
            'context': {'create': False},
            'target': 'current',
        }

    def action_refresh_status(self):
        """Action pour rafraîchir le statut depuis Orange Money"""
        try:
            config = self.env['orange.money.config'].search([('is_active', '=', True)], limit=1)
            if not config:
                raise ValidationError("Aucune configuration Orange Money active trouvée.")
            
            _logger.info(f"Transaction ID: {self.qr_id}")
            status_data = config.get_transaction_status(self.transaction_id)
            
            if status_data:
                status = status_data.get('status', '').upper()
                
                if status and status != self.status:
                    old_status = self.status
                    self.write({
                        'status': status,
                        'orange_response': json.dumps(status_data),
                        'status_reason': status_data.get('statusReason', ''),
                    })
                    
                    # Poster un message de changement de statut
                    self.message_post(
                        body=f"Statut mis à jour de '{old_status}' vers '{status}'",
                        message_type='notification'
                    )
                    
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Statut mis à jour',
                            'message': f'Cle publique ',
                            'type': 'success',
                        }
                    }
                else:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Aucun changement',
                            'message': f'Le statut est déjà à jour: {self.status}',
                            'type': 'info',
                        }
                    }
            else:
                raise ValidationError("Impossible de récupérer les données de statut Orange Money")
                
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Erreur',
                    'message': f'Erreur lors de la mise à jour: {str(e)}',
                    'type': 'danger',
                }
            }

    def create_payment_invoice(self, amount, currency, account_move_id, transaction_id, customer_msisdn, description, reference, success_url , cancel_url=None):
        """
        Crée un ordre de paiement Orange Money en utilisant la méthode generate_qr_code.
        Cette méthode est appelée par le contrôleur.
        """
        try:
            metadata = {
                "account_move_id": str(account_move_id),
                "transaction_id": transaction_id,
                "customer_msisdn": customer_msisdn,
                "description": description,
                "reference": reference,
                "success_url": success_url,
            }
            
            # Appeler la méthode existante pour générer le QR code
            qr_data = self.generate_qr_code(
                amount=amount,
                metadata=metadata,
                success_url=success_url,
                cancel_url=cancel_url,
            )
            _logger.info(f"QR data: {qr_data}")
           
            if qr_data:
                # Extraire toutes les informations pertinentes de la réponse Orange Money
                deep_links = qr_data.get('deepLinks', {})
                valid_for = qr_data.get('validFor', {})
                deep_link = qr_data.get('deepLink')
                maxit = qr_data.get('deepLinks', {}).get('MAXIT')
                om = qr_data.get('deepLinks', {}).get('OM')
                qr_code = qr_data.get('qrCode')
                qr_id = qr_data.get('qrId')
                short_link = qr_data.get('shortLink')
                validity = qr_data.get('validity')
                valid_for = qr_data.get('validFor', {})
                end_date_time = valid_for.get('endDateTime')
                start_date_time = valid_for.get('startDateTime')
                callback_url = self.callback_notification_url
            

                # Convertir les dates au format correct
                def format_datetime(dt_str):
                    if dt_str:
                        dt = datetime.strptime(dt_str, '%Y-%m-%dT%H:%M:%S.%f')
                        return dt.strftime('%Y-%m-%d %H:%M:%S')
                    return None

                start_date_time = format_datetime(start_date_time)
                end_date_time = format_datetime(end_date_time)


                # api_transaction_model = self.env['orange.money.api.transaction']
                # api_transaction_model.fetch_all_transactions()


                return {
                    'success': True,
                    'pay_token': qr_id,
                    'qr_id': qr_id,
                    'payment_url': deep_link,
                    'deep_link': deep_link,
                    'qr_code_base64': qr_code,
                    'deep_link_om': om,
                    'deep_link_maxit': maxit,
                    'short_link': short_link,
                    'validity_seconds': validity,
                    'valid_from': start_date_time,
                    'valid_until': end_date_time,
                    'orange_response': json.dumps(qr_data),
                    'callback_url': callback_url
                }
            else:
                return {'success': False, 'message': 'Failed to generate QR code'}
        except Exception as e:
            _logger.error(f"Error in create_payment_order: {str(e)}")
            return {'success': False, 'message': str(e)}

    def get_payment_status_by_token(self, pay_token):
        """
        Récupère le statut d'une transaction Orange Money en utilisant le pay_token.
        Cette méthode est appelée par le contrôleur.
        """
        try:
            # Trouver la transaction Odoo par pay_token
            transaction_odoo = self.env['orange.money.transaction'].sudo().search([('pay_token', '=', pay_token)], limit=1)
            
            if not transaction_odoo:
                _logger.warning(f"No Odoo transaction found for pay_token: {pay_token}")
                return None
            
            # Utiliser le transaction_id de la transaction Odoo pour interroger l'API Orange Money
            status_data = self.get_transaction_status(transaction_odoo.qr_id)
            
            if status_data:
                return status_data
            else:
                return None
        except Exception as e:
            _logger.error(f"Error in get_payment_status_by_token for pay_token {pay_token}: {str(e)}")
            return None

    # Actions pour les vues
    def action_view_transactions(self):
        """Action pour voir toutes les transactions"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Transactions Orange Money',
            'res_model': 'orange.money.transaction',
            'view_mode': 'tree,form',
            'domain': [],
            'context': {'create': False},
            'target': 'current',
        }
    

    def action_register_webhook(self):
        """
        Configurer le webhook côté Orange Money.

        Équivalent à :
        curl --location '<base_url>/api/notification/v1/merchantcallback' \
        --header 'Authorization: Bearer <token>' \
        --header 'Content-Type: application/json' \
        --data-raw '{
          "apiKey": "...",
          "callbackUrl": "...",
          "code": "...",
          "name": "..."
        }'
        """
        self.ensure_one()

        try:
            # 1) Récupérer un token d'accès OAuth2
            token = self._get_access_token()
            if not token:
                raise ValidationError("Impossible d'obtenir un token d'accès OAuth2.")

            # 2) Construire l'URL complète
            # en sandbox : https://api.sandbox.orange-sonatel.com/api/notification/v1/merchantcallback
            # en prod :   https://api.orange-sonatel.com/api/notification/v1/merchantcallback
            url = f"https://api.orange-sonatel.com/api/notification/v1/merchantcallback"

            # 3) Headers
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            }

            # 4) Payload (body JSON)
            payload = {
                "apiKey": self.api_key,
                "callbackUrl": self.callback_notification_url,
                "code": self.merchant_code,          # ex: 562544
                "name": self.merchant_name,          # ex: CCTS
            }

            _logger.info("Enregistrement du webhook Orange Money: URL=%s, payload=%s", url, payload)

            response = requests.post(url, headers=headers, json=payload, timeout=30)

            _logger.info("Réponse webhook Orange: %s - %s", response.status_code, response.text)

            # On garde la dernière réponse sur la config
            self.write({
                'last_webhook_status': f"{response.status_code} - {response.text}"
            })

            if response.status_code not in (200, 201, 202):
                raise ValidationError(
                    f"Échec de l'enregistrement du webhook Orange Money.\n"
                    f"Code HTTP: {response.status_code}\n"
                    f"Réponse: {response.text}"
                )

            # Notif Odoo
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Webhook configuré',
                    'message': 'Le webhook Orange Money a été configuré avec succès.',
                    'type': 'success',
                    'sticky': False,
                }
            }

        except ValidationError:
            raise
        except Exception as e:
            _logger.error("Erreur lors de la configuration du webhook Orange Money: %s", str(e))
            raise ValidationError(f"Erreur lors de la configuration du webhook: {str(e)}")



