

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
import requests
from datetime import datetime
import json

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'


    # Relations
    orange_money_transaction_ids = fields.One2many(
        'orange.money.transaction',
        'account_move_id',
        string='Transactions Orange Money'
    )

    # Champs calculés
    orange_money_transaction_count = fields.Integer(
        string='Nombre de transactions OM',
        compute='_compute_orange_money_stats',
        store=False
    )

    orange_money_total_paid = fields.Float(
        string='Total payé via Orange Money',
        compute='_compute_orange_money_stats',
        store=False
    )

    orange_money_payment_status = fields.Selection([
        ('none', 'Aucun paiement'),
        ('partial', 'Paiement partiel'),
        ('full', 'Entièrement payé'),
        ('overpaid', 'Surpayé')
    ], string='Statut paiement OM', compute='_compute_orange_money_stats', store=False)

    has_orange_money_config = fields.Boolean(
        string='Configuration OM disponible',
        compute='_compute_has_orange_money_config',
        store=False
    )

    @api.depends('orange_money_transaction_ids', 'orange_money_transaction_ids.status', 'orange_money_transaction_ids.amount')
    def _compute_orange_money_stats(self):
        """Calculer les statistiques des paiements Orange Money"""
        for order in self:
            transactions = order.orange_money_transaction_ids.filtered(lambda t: t.status == 'SUCCESS')
            order.orange_money_transaction_count = len(order.orange_money_transaction_ids)
            order.orange_money_total_paid = sum(transactions.mapped('amount'))

            # Déterminer le statut de paiement
            if order.orange_money_total_paid == 0:
                order.orange_money_payment_status = 'none'
            elif order.orange_money_total_paid < order.amount_total:
                order.orange_money_payment_status = 'partial'
            elif order.orange_money_total_paid == order.amount_total:
                order.orange_money_payment_status = 'full'
            else:
                order.orange_money_payment_status = 'overpaid'

    def _compute_has_orange_money_config(self):
        """Vérifier si une configuration Orange Money est disponible"""
        for order in self:
            config = self.env['orange.money.config'].search([('is_active', '=', True)], limit=1)
            order.has_orange_money_config = bool(config)

    def action_initiate_orange_money_payment(self):
        """Action pour initier un paiement Orange Money"""
        self.ensure_one()

        # Validation
        validation_result = self._validate_orange_money_payment()
        if not validation_result['success']:
            return self._show_notification('Erreur de validation', validation_result['message'], 'danger')

        # Générer un ID de transaction unique
        transaction_id = self._generate_transaction_id()

        # Préparer les données de paiement
        payment_data = self._prepare_payment_data(transaction_id)

        try:
            # Initier le paiement
            response = self._initiate_orange_money_payment(payment_data)

            if response.get('success'):
                return self._handle_payment_success(response, payment_data)
            else:
                return self._handle_payment_error(response)

        except Exception as e:
            _logger.error(f"Erreur lors de l'initiation du paiement Orange Money pour la facture {self.name}: {str(e)}")
            return self._show_notification(
                'Erreur système',
                f'Une erreur inattendue s\'est produite: {str(e)}',
                'danger'
            )

    def _validate_orange_money_payment(self):
        """Valider les conditions pour initier un paiement Orange Money"""
        # Vérifier la configuration
        config = self.env['orange.money.config'].search([('is_active', '=', True)], limit=1)
        if not config:
            return {'success': False, 'message': 'Aucune configuration Orange Money active trouvée.'}

        # Valider le code marchand
        merchant_code = str(config.merchant_code).strip()
        merchant_code_digits = ''.join(filter(str.isdigit, merchant_code))

        if len(merchant_code_digits) != 6:
            return {
                'success': False,
                'message': f'Le code marchand doit contenir exactement 6 chiffres. Code actuel: "{config.merchant_code}" contient {len(merchant_code_digits)} chiffres.'
            }

        # Vérifier l'état de la facture
        if self.state not in ['draft', 'sent', 'sale']:
            return {'success': False, 'message': 'La facture doit être en état brouillon, envoyée ou confirmée.'}

        # Vérifier le montant
        if self.amount_total <= 0:
            return {'success': False, 'message': 'Le montant de la facture doit être supérieur à zéro.'}

        # Vérifier le partenaire
        if not self.partner_id:
            return {'success': False, 'message': 'Un client doit être sélectionné.'}

        return {'success': True}

    def _generate_transaction_id(self):
        """Générer un ID de transaction unique"""
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        return f"OM-{self.id}-{timestamp}-{self.amount_total}"

    def _prepare_payment_data(self, transaction_id):
        """Préparer les données pour le paiement"""
        success_url_new = f"https://portail.toubasandaga.sn/om-paiement?transaction={transaction_id}"
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

        return {
            'transaction_id': transaction_id,
            'account_move_id': self.id,
            'partner_id': self.partner_id.id,
            'phone_number': self.partner_id.phone or '',
            'amount': self.amount_total,
            'description': f"Paiement pour la facture {self.name}",
            'currency': self.currency_id.name,
            'reference': f"REF-{self.name}-{timestamp}",
            'success_url': success_url_new
        }

    def _initiate_orange_money_payment(self, payment_data):
        """Initier un paiement Orange Money avec QR code"""
        try:
            # Récupérer la configuration
            config = self.env['orange.money.config'].sudo().search([('is_active', '=', True)], limit=1)

            # Vérifier si la transaction existe déjà
            existing_tx = self.env['orange.money.transaction'].sudo().search([
                ('transaction_id', '=', payment_data['transaction_id'])
            ], limit=1)

            if existing_tx:
                return self._handle_existing_transaction(existing_tx, payment_data)

            # Obtenir le token d'accès
            token = config._get_access_token()

            # Préparer le payload pour l'API Orange Money
            payload = self._prepare_api_payload(config, payment_data)

            # Effectuer l'appel API
            response = self._call_orange_money_api(config, token, payload)

            if response.status_code in [200, 201]:
                return self._process_api_success(response, payment_data, config)
            else:
                return self._process_api_error(response)

        except Exception as e:
            _logger.error(f"Erreur lors de l'initiation du paiement Orange Money: {str(e)}")
            return {'error': str(e), 'success': False}

    def _handle_existing_transaction(self, existing_tx, payment_data):
        """Gérer une transaction existante"""
        return {
            'success': True,
            'transaction_id': existing_tx.transaction_id,
            'orange_id': existing_tx.orange_id,
            'qr_code_url': existing_tx.qr_code_url or existing_tx.deep_link,
            'existing': True
        }

    def _prepare_api_payload(self, config, payment_data):
        """Préparer le payload pour l'API Orange Money"""
        # Valider et formater le code marchand
        merchant_code = str(config.merchant_code).strip()
        merchant_code = ''.join(filter(str.isdigit, merchant_code))

        if len(merchant_code) != 6:
            raise ValidationError(f"Le code marchand doit contenir exactement 6 chiffres.")

        return {
            "amount": {
                "unit": payment_data['currency'],
                "value": int(payment_data['amount'])
            },
            "code": merchant_code,
            "name": config.merchant_name,
            "validity": 3600,  # 1 heure
            "callbackSuccessUrl": payment_data['success_url'],
            "callbackCancelUrl": payment_data['success_url'],
            "reference": payment_data['reference'],
            "metadata": {
                "account_move_id": str(payment_data['account_move_id']),
                "partner_id": str(payment_data['partner_id']),
                "transaction_id": payment_data['transaction_id'],
                "phone_number": payment_data['phone_number'],
            }
        }

    def _call_orange_money_api(self, config, token, payload):
        """Effectuer l'appel à l'API Orange Money"""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Callback-Url": config.callback_notification_url
        }

        return requests.post(
            f"{config.base_url}/api/eWallet/v4/qrcode",
            json=payload,
            headers=headers,
            timeout=30
        )

    def _process_api_success(self, response, payment_data, config):
        """Traiter une réponse API réussie"""
        data = response.json()

        # Créer la transaction dans Odoo
        transaction_data = {
            'success_url': payment_data.get('success_url', 'https://portail.toubasandaga.sn/'),
            'cancel_url': payment_data.get('success_url', 'https://portail.toubasandaga.sn/'),
            'callback_url': payment_data.get('callback_url', 'https://intranet.toubasandaga.sn/api/orange/callback/{transaction_id}'),
            'pay_token': data.get('pay_token'),
            'transaction_id': payment_data['transaction_id'],
            'amount': payment_data['amount'],
            'currency': payment_data['currency'],
            'status': 'INITIATED',
            'customer_msisdn': payment_data['phone_number'],
            'merchant_code': config.merchant_code,
            'reference': payment_data['reference'],
            'description': payment_data['description'],
            'payment_url': data.get('payment_url'),
            'qr_code_url': data.get('deepLink'),
            'qr_code_base64': data.get('qrCode'),
            'qr_id': data.get('qrId'),
            'deep_link': data.get('deepLink'),
            'deep_link_om': data.get('deepLinkOm'),
            'deep_link_maxit': data.get('deepLinkMaxit'),
            'short_link': data.get('shortLink'),
            'validity_seconds': data.get('validitySeconds'),
            'valid_from': data.get('validFrom'),
            'valid_until': data.get('validUntil'),
            'orange_response': json.dumps(data),
            'metadata': json.dumps(data.get('metadata', {})),
            'account_move_id': self.id,
            'partner_id': self.partner_id.id,
            'orange_id': data.get('qrId'),
        }

        try:
            # Créer un point de sauvegarde
            savepoint_name = self.env.cr.savepoint()

            try:
                orange_transaction = self.env['orange.money.transaction'].sudo().create(transaction_data)
                self.env.cr.commit()  # Valider la transaction
            except Exception as e:
                self.env.cr.rollback(savepoint_name)  # Annuler la transaction en cas d'erreur
                _logger.error(f"Erreur lors de la création de la transaction: {str(e)}")
                raise UserError(f"Erreur lors de la création de la transaction: {str(e)}")

        except Exception as e:
            _logger.error(f"Erreur lors de la gestion du point de sauvegarde: {str(e)}")
            raise UserError(f"Erreur lors de la gestion du point de sauvegarde: {str(e)}")

        return {
            'success': True,
            'transaction_id': orange_transaction.transaction_id,
            'orange_id': data.get('qrId'),
            'qr_code_url': data.get('deepLink'),
            'status': 'INITIATED'
        }

    def _process_api_error(self, response):
        """Traiter une erreur API"""
        try:
            error_data = response.json()
            error_message = error_data.get('detail', error_data.get('message', response.text))
        except:
            error_message = response.text

        _logger.error(f"Orange Money API Error: {response.status_code} - {error_message}")
        return {
            'error': f"Erreur API Orange Money: {response.status_code}",
            'message': error_message,
            'success': False
        }

    def _handle_payment_success(self, response, payment_data):
        """Gérer le succès de l'initiation du paiement"""
        return self._show_notification(
            'Paiement initié',
            f'Paiement Orange Money initié avec succès. Transaction ID: {response.get("transaction_id")}',
            'success'
        )

    def _handle_payment_error(self, response):
        """Gérer les erreurs de paiement"""
        error_message = response.get('message', response.get('error', 'Erreur inconnue'))
        return self._show_notification('Erreur de paiement', error_message, 'danger')

    def _show_notification(self, title, message, notification_type):
        """Afficher une notification"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notification_type,
            }
        }

    def action_view_orange_money_transactions(self):
        """Action pour voir les transactions Orange Money de cette facture"""
        self.ensure_one()

        return {
            'name': f'Transactions Orange Money - {self.name}',
            'type': 'ir.actions.act_window',
            'view_mode': 'tree,form',
            'res_model': 'orange.money.transaction',
            'domain': [('account_move_id', '=', self.id)],
            'context': {
                'default_account_move_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_amount': self.amount_total,
                'default_currency': self.currency_id.name,
                'default_reference': self.name,
            },
            'target': 'current',
        }

    def get_invoice_details(self):
        """Renvoyer les détails du paiement"""
        if not self.payment_link:
            raise ValidationError("Aucun lien de paiement associé à cette facture.")
        
        line_items = []
        for line in self.invoice_line_ids:
            line_items.append({
                'id': line.id,
                'name': line.name,
                'quantity': line.quantity,
                'price_unit': line.price_unit,
                'price_subtotal': line.price_subtotal,
                'account': line.account_id.name
            })

        return {
            'id': self.id,
            'name': self.name,
            'stats': self.state,
            'paid': self.payment_state,
            'transaction_id': self.transaction_id,
            'payment_link': self.payment_link,
            'partner_id': self.partner_id.id,
            'amount': self.amount_residual,
            'currency': self.currency_id.name,
            'invoice_date': self.invoice_date.isoformat() if self.invoice_date else None,
            'invoice_number': self.name,
            'line_items': line_items,
            'partner':{
                'id': self.partner_id.id,
                'name': self.partner_id.name,
                'email': self.partner_id.email,
                'phone': self.partner_id.phone,
                'mobile': self.partner_id.mobile,
                'adress': self.partner_id.city
            }
        }
    

    def action_view_orange_transactions(self):
        self.ensure_one()
        return {
            'name': 'Transactions Orange Money',
            'type': 'ir.actions.act_window',
            'view_mode': 'tree,form',
            'res_model': 'orange.money.transaction',
            'domain': [('account_move_id', '=', self.id)],
        }